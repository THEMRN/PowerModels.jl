### rectangular form of the non-convex AC equations

""
function variable_bus_voltage(pm::AbstractQCAPModel; nw::Int=nw_id_default, bounded::Bool=true, kwargs...)
    variable_bus_voltage_real(pm; nw=nw, bounded=bounded, kwargs...)
    variable_bus_voltage_imaginary(pm; nw=nw, bounded=bounded, kwargs...)
    Rho = get(kwargs, :Rho, 1.0)
    if Rho!=0.0
        variable_bus_voltage_magnitude_sqr(pm; nw=nw, bounded=bounded, kwargs...)
        variable_buspair_voltage_product(pm; nw=nw, bounded=bounded, kwargs...)  
        variable_Khi(pm; nw=nw, bounded=bounded, kwargs...)

        w = var(pm, nw)[:w]
        vr = var(pm, nw)[:vr]
        vi = var(pm, nw)[:vi]
        wr = var(pm, nw)[:wr]
        wi = var(pm, nw)[:wi] 
        Khi_c_i = var(pm, nw)[:Khi_c_i]
        Khi_c_ij = var(pm, nw)[:Khi_c_ij]
        Khi_s_ij = var(pm, nw)[:Khi_s_ij]
        # Access and print the value of w[i]
        for i in ids(pm, nw, :bus)
            JuMP.@constraint(pm.model, w[i] >= vr[i]^2 + vi[i]^2)
            JuMP.@constraint(pm.model, 
            w[i] <= 2 * (JuMP.start_value(vr[i]) * vr[i] + JuMP.start_value(vi[i]) * vi[i]) 
                   - (JuMP.start_value(vr[i])^2 + JuMP.start_value(vi[i])^2) 
                   + Khi_c_i[i]
        )
                
        end
        for bp in ids(pm, nw, :buspairs)

            i,j = bp
            # println(JuMP.start_value(vr[i]))
            JuMP.@constraint(pm.model,  (vr[i] + vr[j])^2+ (vi[i] + vi[j])^2-4*wr[bp]<=Khi_c_ij[bp]+2*(vr[i] - vr[j])*(JuMP.start_value(vr[i])-JuMP.start_value(vr[j]))+2*(vi[i] - vi[j])*(JuMP.start_value(vi[i])-JuMP.start_value(vi[j]))-((JuMP.start_value(vr[i])-JuMP.start_value(vr[j]))^2 + (JuMP.start_value(vi[i])-JuMP.start_value(vi[j]))^2))
            JuMP.@constraint(pm.model,  (vr[i] - vr[j])^2+ (vi[i] - vi[j])^2+4*wr[bp]<=Khi_c_ij[bp]+2*(vr[i] + vr[j])*(JuMP.start_value(vr[i])+JuMP.start_value(vr[j]))+2*(vi[i] + vi[j])*(JuMP.start_value(vi[i])+JuMP.start_value(vi[j]))-((JuMP.start_value(vr[i])+JuMP.start_value(vr[j]))^2 + (JuMP.start_value(vi[i])+JuMP.start_value(vi[j]))^2))
            JuMP.@constraint(pm.model,  (vr[i] - vi[j])^2+ (vr[j] + vi[i])^2+4*wi[bp]<=Khi_s_ij[bp]+2*(vr[i] + vi[j])*(JuMP.start_value(vr[i])+JuMP.start_value(vi[j]))+2*(vr[j] - vi[i])*(JuMP.start_value(vr[j])-JuMP.start_value(vi[i]))-((JuMP.start_value(vr[i])+JuMP.start_value(vi[j]))^2 + (JuMP.start_value(vr[j])-JuMP.start_value(vr[i]))^2))
            JuMP.@constraint(pm.model,  (vr[i] + vi[j])^2+ (vr[j] - vi[i])^2-4*wi[bp]<=Khi_s_ij[bp]+2*(vr[i] - vi[j])*(JuMP.start_value(vr[i])-JuMP.start_value(vi[j]))+2*(vr[j] + vi[i])*(JuMP.start_value(vr[j])+JuMP.start_value(vi[i]))-((JuMP.start_value(vr[i])-JuMP.start_value(vi[j]))^2 + (JuMP.start_value(vr[j])+JuMP.start_value(vr[i]))^2))

        end
    end

 

    
    if bounded
        for (i,bus) in ref(pm, nw, :bus)
            constraint_voltage_magnitude_bounds(pm, i, nw=nw)
        end
        # for bp in ids(pm, nw, :buspairs)
        #    i,j = bp
        #    println("buspair: ", bp, " ", i, " ", j)

        # end

        # does not seem to improve convergence
        #wr_min, wr_max, wi_min, wi_max = ref_calc_voltage_product_bounds(pm.ref[:buspairs])
        #for bp in ids(pm, nw, :buspairs)
        #    i,j = bp
        #    JuMP.@constraint(pm.model, wr_min[bp] <= vr[i]*vr[j] + vi[i]*vi[j])
        #    JuMP.@constraint(pm.model, wr_max[bp] >= vr[i]*vr[j] + vi[i]*vi[j])
        #
        #    JuMP.@constraint(pm.model, wi_min[bp] <= vi[i]*vr[j] - vr[i]*vi[j])
        #    JuMP.@constraint(pm.model, wi_max[bp] >= vi[i]*vr[j] - vr[i]*vi[j])
        #end
    end
end


"`vmin <= vm[i] <= vmax`"
function constraint_voltage_magnitude_bounds(pm::AbstractQCAPModel, n::Int, i, vmin, vmax)
    @assert vmin <= vmax
    vr = var(pm, n, :vr, i)
    vi = var(pm, n, :vi, i)

    JuMP.@constraint(pm.model, vmin^2 <= (vr^2 + vi^2) <= vmax^2)
end


"reference bus angle constraint"
function constraint_theta_ref(pm::AbstractQCAPModel, n::Int, i::Int)

    JuMP.@constraint(pm.model, var(pm, n, :vi)[i] == 0)
end


function constraint_power_balance(pm::AbstractQCAPModel, n::Int, i::Int, bus_arcs, bus_arcs_dc, bus_arcs_sw, bus_gens, bus_storage, bus_pd, bus_qd, bus_gs, bus_bs)

    vr = var(pm, n, :vr, i)
    vi = var(pm, n, :vi, i)
    p    = get(var(pm, n),    :p, Dict()); _check_var_keys(p, bus_arcs, "active power", "branch")
    q    = get(var(pm, n),    :q, Dict()); _check_var_keys(q, bus_arcs, "reactive power", "branch")
    pg   = get(var(pm, n),   :pg, Dict()); _check_var_keys(pg, bus_gens, "active power", "generator")
    qg   = get(var(pm, n),   :qg, Dict()); _check_var_keys(qg, bus_gens, "reactive power", "generator")
    ps   = get(var(pm, n),   :ps, Dict()); _check_var_keys(ps, bus_storage, "active power", "storage")
    qs   = get(var(pm, n),   :qs, Dict()); _check_var_keys(qs, bus_storage, "reactive power", "storage")
    psw  = get(var(pm, n),  :psw, Dict()); _check_var_keys(psw, bus_arcs_sw, "active power", "switch")
    qsw  = get(var(pm, n),  :qsw, Dict()); _check_var_keys(qsw, bus_arcs_sw, "reactive power", "switch")
    p_dc = get(var(pm, n), :p_dc, Dict()); _check_var_keys(p_dc, bus_arcs_dc, "active power", "dcline")
    q_dc = get(var(pm, n), :q_dc, Dict()); _check_var_keys(q_dc, bus_arcs_dc, "reactive power", "dcline")


    cstr_p = JuMP.@constraint(pm.model,
        sum(p[a] for a in bus_arcs)
        + sum(p_dc[a_dc] for a_dc in bus_arcs_dc)
        + sum(psw[a_sw] for a_sw in bus_arcs_sw)
        ==
        sum(pg[g] for g in bus_gens)
        - sum(ps[s] for s in bus_storage)
        - sum(pd for pd in values(bus_pd))
        - sum(gs for gs in values(bus_gs))*(vr^2 + vi^2)
    )
    cstr_q = JuMP.@constraint(pm.model,
        sum(q[a] for a in bus_arcs)
        + sum(q_dc[a_dc] for a_dc in bus_arcs_dc)
        + sum(qsw[a_sw] for a_sw in bus_arcs_sw)
        ==
        sum(qg[g] for g in bus_gens)
        - sum(qs[s] for s in bus_storage)
        - sum(qd for qd in values(bus_qd))
        + sum(bs for bs in values(bus_bs))*(vr^2 + vi^2)
    )

    if _IM.report_duals(pm)
        sol(pm, n, :bus, i)[:lam_kcl_r] = cstr_p
        sol(pm, n, :bus, i)[:lam_kcl_i] = cstr_q
    end
end

""


""


""



"""
Creates Ohms constraints (yt post fix indicates that Y and T values are in rectangular form)
"""
function constraint_ohms_yt_from(pm::AbstractQCAPModel, n::Int, f_bus, t_bus, f_idx, t_idx, g, b, g_fr, b_fr, tr, ti, tm)

    p_fr = var(pm, n, :p, f_idx)
    q_fr = var(pm, n, :q, f_idx)
    vr_fr = var(pm, n, :vr, f_bus)
    vr_to = var(pm, n, :vr, t_bus)
    vi_fr = var(pm, n, :vi, f_bus)
    vi_to = var(pm, n, :vi, t_bus)

    JuMP.@constraint(pm.model, p_fr ==  (g+g_fr)/tm^2*(vr_fr^2 + vi_fr^2) + (-g*tr+b*ti)/tm^2*(vr_fr*vr_to + vi_fr*vi_to) + (-b*tr-g*ti)/tm^2*(vi_fr*vr_to - vr_fr*vi_to) )
    JuMP.@constraint(pm.model, q_fr == -(b+b_fr)/tm^2*(vr_fr^2 + vi_fr^2) - (-b*tr-g*ti)/tm^2*(vr_fr*vr_to + vi_fr*vi_to) + (-g*tr+b*ti)/tm^2*(vi_fr*vr_to - vr_fr*vi_to) )
end

"""
Creates Ohms constraints (yt post fix indicates that Y and T values are in rectangular form)
"""
function constraint_ohms_yt_to(pm::AbstractQCAPModel, n::Int, f_bus, t_bus, f_idx, t_idx, g, b, g_to, b_to, tr, ti, tm)
    p_to = var(pm, n, :p, t_idx)
    q_to = var(pm, n, :q, t_idx)
    vr_fr = var(pm, n, :vr, f_bus)
    vr_to = var(pm, n, :vr, t_bus)
    vi_fr = var(pm, n, :vi, f_bus)
    vi_to = var(pm, n, :vi, t_bus)

    JuMP.@constraint(pm.model, p_to ==  (g+g_to)*(vr_to^2 + vi_to^2) + (-g*tr-b*ti)/tm^2*(vr_fr*vr_to + vi_fr*vi_to) + (-b*tr+g*ti)/tm^2*(-(vi_fr*vr_to - vr_fr*vi_to)) )
    JuMP.@constraint(pm.model, q_to == -(b+b_to)*(vr_to^2 + vi_to^2) - (-b*tr+g*ti)/tm^2*(vr_fr*vr_to + vi_fr*vi_to) + (-g*tr-b*ti)/tm^2*(-(vi_fr*vr_to - vr_fr*vi_to)) )
end


""

"""
branch voltage angle difference bounds
"""

function constraint_voltage_angle_difference(pm::AbstractQCAPModel, n::Int, f_idx, angmin, angmax)
    i, f_bus, t_bus = f_idx

    vr_fr = var(pm, n, :vr, f_bus)
    vr_to = var(pm, n, :vr, t_bus)
    vi_fr = var(pm, n, :vi, f_bus)
    vi_to = var(pm, n, :vi, t_bus)

    JuMP.@constraint(pm.model, (vi_fr*vr_to - vr_fr*vi_to) <= tan(angmax)*(vr_fr*vr_to + vi_fr*vi_to))
    JuMP.@constraint(pm.model, (vi_fr*vr_to - vr_fr*vi_to) >= tan(angmin)*(vr_fr*vr_to + vi_fr*vi_to))
end

""
function sol_data_model!(pm::AbstractQCAPModel, solution::Dict)
    apply_pm!(_sol_data_model_qcap!, solution)
end


""
function _sol_data_model_qcap!(solution::Dict)

    if haskey(solution, "bus")
        for (i, bus) in solution["bus"]
            if haskey(bus, "vr") && haskey(bus, "vi")
                bus["vm"] = sqrt(bus["vr"]^2 + bus["vi"]^2)
                bus["va"] = atan(bus["vi"], bus["vr"])

                delete!(bus, "vr")
                delete!(bus, "vi")
            end
        end
    end
end
