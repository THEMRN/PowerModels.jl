"""
FRQTPAT, the PSS®E under/over frequency generator trip relay, as an ANDES model.

PSS®E record (Model Library, Miscellaneous Other Models):

    MINS, 'FRQTPAT', monitored bus, generator bus, generator ID, FL, FU, TP, TB /

The relay picks up once the frequency at the monitored bus has stayed below FL or above FU (Hz)
for TP seconds without interruption, and its breaker trips the generator TB seconds later, whatever
the frequency does in between. A monitored bus of 0 is read as the generator bus.

Only the frequency input is declared for code generation; the relay logic is plain Python in
`s_numeric_var`. Editing the logic needs no `prepare_models.py`, editing the parameters or
variables does.
"""

import logging

import numpy as np
from andes.core.model import Model, ModelData
from andes.core.param import ExtParam, IdxParam, NumParam
from andes.core.var import ExtAlgeb

logger = logging.getLogger(__name__)


class FRQTPATData(ModelData):
    """FRQTPAT parameters, one device per relay record."""

    def __init__(self):
        super().__init__()
        self.busfreq = IdxParam(model="BusFreq", info="BusFreq device at the monitored bus", mandatory=True)
        self.syn = IdxParam(
            model="SynGen",
            info="synchronous machine to trip",
            mandatory=True,
            status_parent=True,  # the relay goes offline with its machine
        )
        self.FL = NumParam(info="lower frequency threshold", unit="Hz", tex_name="F_L", mandatory=True)
        self.FU = NumParam(info="upper frequency threshold", unit="Hz", tex_name="F_U", mandatory=True)
        self.TP = NumParam(default=0.0, info="relay pickup time", unit="s", tex_name="T_P", non_negative=True)
        self.TB = NumParam(default=0.0, info="breaker time", unit="s", tex_name="T_B", non_negative=True)


class FRQTPAT(FRQTPATData, Model):
    """
    Under/over frequency generator trip relay (PSSE FRQTPAT). The trips of a run are kept in
    `trips`, one dict per tripped machine.
    """

    def __init__(self, system, config):
        FRQTPATData.__init__(self)
        Model.__init__(self, system, config)
        self.flags.update({"tds": True, "sv_num": True})
        self.group = "Undefined"  # ANDES has no group for relays

        self.fn = ExtParam(model="BusFreq", src="fn", indexer=self.busfreq, export=False, unit="Hz")
        self.f = ExtAlgeb(
            model="BusFreq",
            src="f",
            indexer=self.busfreq,
            export=False,
            info="monitored frequency",
            unit="pu",
        )

        # relay memory, cleared when the dynamic simulation is initialized
        self.pickup_start = np.array([])  # s, when the frequency left [FL, FU]
        self.breaker_open_time = np.array([])  # s, set at pickup
        self.t_checked = 0.0  # s, the time step the logic last ran for
        self.trips = []

    def v_numeric(self, **kwargs):
        """Clears the relay memory at the initialization of the dynamic simulation."""
        # ADNES calls this hook at the start of a dynamic simulation, before the first time step.
        self.pickup_start = np.full(self.n, np.nan)
        self.breaker_open_time = np.full(self.n, np.nan)
        self.t_checked = 0.0
        self.trips = []

    def s_numeric_var(self, **kwargs):
        """
        Relay logic, once per time step. ANDES calls this hook before every Newton iteration; the
        first call of a step still sees the converged values of the previous step, at t - h, so the
        later calls are skipped and a trip takes effect from that previous step on.
        """
        # ANDES calls this before every Newton iteration, because sv_num flag is set
        t = float(self.system.dae.t)
        if t <= 0.0 or t == self.t_checked:
            return
        self.t_checked = t
        t_measured = t - self.system.TDS.h  # s, time of the values seen now
        frequency = self.f.v * self.fn.v  # Hz

        for i in range(self.n):
            if self.ue.v[i] == 0:
                continue  # machine offline or already tripped

            # pickup: the frequency stays outside [FL, FU] for TP
            if np.isnan(self.breaker_open_time[i]):
                outside_band = frequency[i] < self.FL.v[i] or frequency[i] > self.FU.v[i]
                if not outside_band:
                    self.pickup_start[i] = np.nan
                    continue
                if np.isnan(self.pickup_start[i]):
                    self.pickup_start[i] = t_measured
                if t_measured - self.pickup_start[i] < self.TP.v[i]:
                    continue
                self.breaker_open_time[i] = t_measured + self.TB.v[i]

            # breaker: opens TB after pickup
            if t_measured < self.breaker_open_time[i]:
                continue
            self.trip_machine(i, t_measured, frequency[i])

    def trip_machine(self, i, t_trip, frequency_hz):
        """
        Takes the machine of relay `i` offline (its exciter and governor follow) and records the
        trip. `custom_event` makes ANDES rebuild the Jacobian and run the switch actions.
        """
        system = self.system
        machine = self.syn.v[i]
        machine_bus = int(system.SynGen.get(src="bus", idx=machine))
        power_mw = system.SynGen.get(src="Pe", idx=machine) * system.config.mva

        system.set_status("SynGen", machine, 0)  # machine offline
        system.TDS.custom_event = True  # to rebuild Jacobian

        self.trips.append(
            {
                "time": t_trip,  # s
                "relay": self.name.v[i],
                "machine": machine,
                "bus": machine_bus,
                "frequency": frequency_hz,  # Hz
                "MW": power_mw,  # electrical power just before the trip
            }
        )
        logger.info(
            "<FRQTPAT %s>: tripped %s at bus %s at t=%.4f s, f=%.3f Hz, %.1f MW.",
            self.name.v[i],
            machine,
            machine_bus,
            t_trip,
            frequency_hz,
            power_mw,
        )


def find_machines_by_bus_and_id(ss):
    """ANDES synchronous machine idx keyed by (bus number, machine id string), the PSS®E key."""
    static_gen_ids = {}
    for gen_model in (ss.PV, ss.Slack):
        for gen_idx, gen_id in zip(gen_model.idx.v, gen_model.subidx.v):
            static_gen_ids[gen_idx] = str(gen_id).strip()

    machines = {}
    for machine_model in (ss.GENROU, ss.GENCLS):  # GENSAL is read as GENROU
        for machine_idx, bus, static_gen in zip(machine_model.idx.v, machine_model.bus.v, machine_model.gen.v):
            machines[(int(bus), static_gen_ids[static_gen])] = machine_idx
    return machines


def add_frqtpat_relays(ss, busfreq_by_bus):
    """
    Adds one FRQTPAT device per FRQTPAT record of the dyr, before `ss.setup()`. ANDES keeps the
    records of the models it doesn't read in `ss.dyr_dict`. `busfreq_by_bus` maps a bus number to
    the idx of its BusFreq device. Returns the number of relays added.
    """
    if "FRQTPAT" not in ss.dyr_dict:
        return 0
    machines = find_machines_by_bus_and_id(ss)

    n_added = 0
    for record in ss.dyr_dict["FRQTPAT"].itertuples(index=False):
        relay_id, monitored_bus, gen_bus, gen_id, FL, FU, TP, TB = record
        if int(monitored_bus) == 0:
            monitored_bus = gen_bus
        machine_key = (int(gen_bus), str(gen_id).strip())
        if machine_key not in machines:
            print(f"-- No machine found for FRQTPAT relay {relay_id} (bus {gen_bus}, id {gen_id}), skipped.")
            continue

        ss.add(
            "FRQTPAT",
            {
                "name": str(relay_id),
                "busfreq": busfreq_by_bus[int(monitored_bus)],
                "syn": machines[machine_key],
                "FL": FL,
                "FU": FU,
                "TP": TP,
                "TB": TB,
            },
        )
        n_added += 1
    return n_added
