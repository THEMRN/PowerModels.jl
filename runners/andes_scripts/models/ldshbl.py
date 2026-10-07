"""
LDSHBL, the PSS®E underfrequency load shedding relay, as an ANDES model.

PSS®E record (Model Library, Load Relay Models):

    bus, 'LDSHBL', load ID, f1, t1, frac1, f2, t2, frac2, f3, t3, frac3, tb /

Each of the three stages picks up once the frequency at the load bus has stayed below its
frequency f (Hz) for its pickup time t (s), and its breaker sheds the fraction frac of the initial
load tb seconds later, whatever the frequency does in between. Each stage acts once. A load ID of
* (or #) applies the record to every load at the bus; here each load gets its own device.

The load is shed by scaling the constants of the converted PQ load (Ipeq, Xeq, ...), which ANDES
computes once, at the initialization of the dynamic simulation. Only the frequency input is
declared for code generation; the relay logic is plain Python in `s_numeric_var`. Editing the logic
needs no `prepare_models.py`, editing the parameters or variables does.
"""

import logging

import numpy as np
from andes.core.model import Model, ModelData
from andes.core.param import DataParam, ExtParam, IdxParam, NumParam
from andes.core.var import ExtAlgeb

logger = logging.getLogger("andes.models.ldshbl")  # under the andes logger, so it reaches the ANDES log

N_STAGES = 3
LOAD_CONSTANTS = ("Ppf", "Qpf", "Req", "Xeq", "Ipeq", "Iqeq")  # PQ constants of the converted load, pu


class LDSHBLData(ModelData):
    """LDSHBL parameters, one device per load."""

    def __init__(self):
        super().__init__()
        self.busfreq = IdxParam(model="BusFreq", info="BusFreq device at the load bus", mandatory=True)
        self.pq = IdxParam(
            model="PQ",
            info="load to shed",
            mandatory=True,
            status_parent=True,  # the relay goes offline with its load
        )
        self.load_id = DataParam(info="PSS®E load ID")
        self.f1 = NumParam(default=0.0, info="first load shedding point", unit="Hz")
        self.t1 = NumParam(default=0.0, info="first point pickup time", unit="s", non_negative=True)
        self.frac1 = NumParam(default=0.0, info="first fraction of load to be shed", non_negative=True)
        self.f2 = NumParam(default=0.0, info="second load shedding point", unit="Hz")
        self.t2 = NumParam(default=0.0, info="second point pickup time", unit="s", non_negative=True)
        self.frac2 = NumParam(default=0.0, info="second fraction of load to be shed", non_negative=True)
        self.f3 = NumParam(default=0.0, info="third load shedding point", unit="Hz")
        self.t3 = NumParam(default=0.0, info="third point pickup time", unit="s", non_negative=True)
        self.frac3 = NumParam(default=0.0, info="third fraction of load to be shed", non_negative=True)
        self.tb = NumParam(default=0.0, info="breaker time", unit="s", non_negative=True)


class LDSHBL(LDSHBLData, Model):
    """
    Underfrequency load shedding relay (PSS®E LDSHBL). The sheds of a run are kept in
    `shed_events`, one dict per stage that acted.
    """

    def __init__(self, system, config):
        LDSHBLData.__init__(self)
        Model.__init__(self, system, config)
        self.flags.update({"tds": True, "sv_num": True})
        self.group = "Undefined"  # ANDES has no group for relays

        self.fn = ExtParam(model="BusFreq", src="fn", indexer=self.busfreq, export=False, unit="Hz")
        self.f = ExtAlgeb(
            model="BusFreq",
            src="f",
            indexer=self.busfreq,
            export=False,
            info="frequency at the load bus",
            unit="pu",
        )

        # stage settings and relay memory, one row per device and one column per stage,
        # set when the dynamic simulation is initialized
        self.stage_frequency = np.empty((0, N_STAGES))  # Hz
        self.stage_pickup_time = np.empty((0, N_STAGES))  # s
        self.stage_fraction = np.empty((0, N_STAGES))  # of the initial load
        self.pickup_start = np.empty((0, N_STAGES))  # s, when the frequency fell below the stage frequency
        self.breaker_open_time = np.empty((0, N_STAGES))  # s, set at pickup
        self.stage_done = np.empty((0, N_STAGES), dtype=bool)
        self.initial_load = {}  # PQ constant name -> initial value of each device's load, pu
        self.served = np.array([])  # fraction of the initial load still in service
        self.t_checked = 0.0  # s, the time step the logic last ran for
        self.shed_events = []

    def v_numeric(self, **kwargs):
        """
        Reads the stage settings and the initial load, and clears the relay memory, at the
        initialization of the dynamic simulation (after PQ has computed its constants).
        """
        self.stage_frequency = np.column_stack([self.f1.v, self.f2.v, self.f3.v])
        self.stage_pickup_time = np.column_stack([self.t1.v, self.t2.v, self.t3.v])
        self.stage_fraction = np.column_stack([self.frac1.v, self.frac2.v, self.frac3.v])
        self.pickup_start = np.full((self.n, N_STAGES), np.nan)
        self.breaker_open_time = np.full((self.n, N_STAGES), np.nan)
        self.stage_done = np.zeros((self.n, N_STAGES), dtype=bool)

        pq = self.system.PQ
        load_uids = pq.idx2uid(list(self.pq.v))
        for name in LOAD_CONSTANTS:
            self.initial_load[name] = getattr(pq, name).v[load_uids].copy()

        self.served = np.ones(self.n)
        self.t_checked = 0.0
        self.shed_events = []

    def s_numeric_var(self, **kwargs):
        """
        Relay logic, once per time step. ANDES calls this hook before every Newton iteration; the
        first call of a step still sees the converged values of the previous step, at t - h, so the
        later calls are skipped and a shed takes effect from that previous step on.
        """
        t = float(self.system.dae.t)
        if t <= 0.0 or t == self.t_checked:
            return
        self.t_checked = t
        t_measured = t - self.system.TDS.h  # s, time of the values seen now
        frequency = self.f.v * self.fn.v  # Hz

        for i in range(self.n):
            if self.ue.v[i] == 0:
                continue  # load offline
            for stage in range(N_STAGES):
                if self.stage_done[i, stage] or self.stage_fraction[i, stage] <= 0.0:
                    continue

                # pickup: the frequency stays below the stage frequency for the stage pickup time
                if np.isnan(self.breaker_open_time[i, stage]):
                    if frequency[i] >= self.stage_frequency[i, stage]:
                        self.pickup_start[i, stage] = np.nan
                        continue
                    if np.isnan(self.pickup_start[i, stage]):
                        self.pickup_start[i, stage] = t_measured
                    if t_measured - self.pickup_start[i, stage] < self.stage_pickup_time[i, stage]:
                        continue
                    self.breaker_open_time[i, stage] = t_measured + self.tb.v[i]

                # breaker: opens tb after pickup
                if t_measured < self.breaker_open_time[i, stage]:
                    continue
                self.shed_load(i, stage, t_measured, frequency[i])

    def shed_load(self, i, stage, t_shed, frequency_hz):
        """
        Sheds the stage fraction of the initial load of relay `i` (no more than what is left) and
        records it. The MW and Mvar shed are that fraction of the converted initial load at 1 pu
        voltage, which is what PSS®E reports (P0/V0 and Q0/V0^2 for constant current P and constant
        admittance Q). `custom_event` makes ANDES rebuild the Jacobian.
        """
        system = self.system
        pq = system.PQ
        load = self.pq.v[i]
        load_uid = pq.idx2uid(load)
        self.stage_done[i, stage] = True

        served_before = self.served[i]
        self.served[i] = max(served_before - self.stage_fraction[i, stage], 0.0)
        shed_fraction = served_before - self.served[i]

        # initial load at 1 pu voltage, from PQ's equations of the dynamic simulation (pu)
        p_initial = (
            pq.config.p2p * self.initial_load["Ppf"][i]
            + pq.config.p2i * self.initial_load["Ipeq"][i]
            + pq.config.p2z * self.initial_load["Req"][i]
        )
        q_initial = (
            pq.config.q2q * self.initial_load["Qpf"][i]
            + pq.config.q2i * self.initial_load["Iqeq"][i]
            + pq.config.q2z * self.initial_load["Xeq"][i]
        )
        p_shed_mw = shed_fraction * p_initial * system.config.mva
        q_shed_mvar = shed_fraction * q_initial * system.config.mva
        v = pq.v.v[load_uid]  # pu, reported only

        for name in LOAD_CONSTANTS:
            pq.set(name, load, self.initial_load[name][i] * self.served[i])
        system.TDS.custom_event = True

        load_bus = int(pq.bus.v[load_uid])
        self.shed_events.append(
            {
                "time": t_shed,  # s
                "load": load,
                "bus": load_bus,
                "load_id": self.load_id.v[i],
                "stage": stage + 1,
                "percent": shed_fraction * 100.0,  # of the initial load
                "MW": p_shed_mw,
                "Mvar": q_shed_mvar,
                "voltage": v,  # pu
                "frequency": frequency_hz,  # Hz
                "served": self.served[i],  # fraction of the initial load left in service
            }
        )
        logger.info(
            "<LDSHBL %s>: bus %s load %s stage %d shed %.2f %% of the initial load at t=%.4f s, "
            "%.2f MW and %.2f Mvar, V=%.3f pu, f=%.3f Hz.",
            self.idx.v[i],
            load_bus,
            self.load_id.v[i],
            stage + 1,
            shed_fraction * 100.0,
            t_shed,
            p_shed_mw,
            q_shed_mvar,
            v,
            frequency_hz,
        )

    def calc_served_fraction(self, load, times):
        """Fraction of the initial load of PQ load `load` in service at each of `times` (s)."""
        served = np.ones(len(times))
        for event in self.shed_events:  # in time order
            if event["load"] != load:
                continue
            served[times > event["time"]] = event["served"]  # the sample at the shed time is before it
        return served


def add_ldshbl_relays(ss, busfreq_by_bus, load_ids):
    """
    Adds one LDSHBL device per load covered by an LDSHBL record of the dyr, before `ss.setup()`.
    ANDES keeps the records of the models it doesn't read in `ss.dyr_dict`. `busfreq_by_bus` maps a
    bus number to the idx of its BusFreq device, `load_ids` holds the RAW load IDs in the order of
    the ANDES PQ loads. Returns the number of relays added.
    """
    if "LDSHBL" not in ss.dyr_dict:
        return 0

    n_added = 0
    for record in ss.dyr_dict["LDSHBL"].itertuples(index=False):
        bus, record_load_id, f1, t1, frac1, f2, t2, frac2, f3, t3, frac3, tb = record
        record_load_id = str(record_load_id).strip()
        all_loads = record_load_id in ("*", "#")

        n_matched = 0
        for load, load_bus, load_id in zip(ss.PQ.idx.v, ss.PQ.bus.v, load_ids):
            if int(load_bus) != int(bus):
                continue
            if not all_loads and load_id != record_load_id:
                continue
            ss.add(
                "LDSHBL",
                {
                    "busfreq": busfreq_by_bus[int(bus)],
                    "pq": load,
                    "load_id": load_id,
                    "f1": f1,
                    "t1": t1,
                    "frac1": frac1,
                    "f2": f2,
                    "t2": t2,
                    "frac2": frac2,
                    "f3": f3,
                    "t3": t3,
                    "frac3": frac3,
                    "tb": tb,
                },
            )
            n_matched += 1
        if n_matched == 0:
            print(f"-- No load found for LDSHBL record at bus {bus} (load {record_load_id}), skipped.")
        n_added += n_matched
    return n_added
