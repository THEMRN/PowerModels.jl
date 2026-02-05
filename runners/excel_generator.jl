using Dates
using XLSX
include("line_flow.jl")

# Create Excel file with multiple sheets
function create_excel_report(result, network_data, filepth="results.xlsx"; powerworld=false)
    # timestamp = Dates.format(Dates.now(), "yyyy-mm-dd_HH-MM-SS")
    # name_parts = splitext(filepth)
    # final_pth = "$(name_parts[1])_$(timestamp)$(name_parts[2])"
    final_pth = filepth

    XLSX.openxlsx("$final_pth", mode="w") do xf
        # Sheet 1: Result summary
        sheet1 = xf[1]
        XLSX.rename!(sheet1, "result")

        # Keys we want from result
        result_keys = ["objective", "solve_time", "primal_status", "dual_status", "termination_status", "optimizer", "objective_lb"]

        # Write headers
        sheet1["A1"] = "Key"
        sheet1["B1"] = "Value"

        # Write data
        row = 2
        for (i, key) in enumerate(result_keys)
            sheet1[XLSX.CellRef(row, 1)] = key
            sheet1[XLSX.CellRef(row, 2)] = string(get(result, key, "N/A"))
            row += 1
        end
        sheet1[XLSX.CellRef(row, 1)] = "Base MVA"
        sheet1[XLSX.CellRef(row, 2)] = network_data["baseMVA"]

        sheet2 = XLSX.addsheet!(xf, "buses")
        bus_headers = ["bus number", "bus type", "vmax", "vmin", "vm", "va (rad)", "va (deg)"]

        # Write bus headers
        for (i, header) in enumerate(bus_headers)
            sheet2[XLSX.CellRef(1, i)] = header
        end

        row = 2
        sorted_buses = sort(collect(result["solution"]["bus"]), by=x -> parse(Int, x[1]))
        for (bus_id, bus_sol) in sorted_buses
            bus_net = network_data["bus"][bus_id]

            sheet2[XLSX.CellRef(row, 1)] = bus_id
            sheet2[XLSX.CellRef(row, 2)] = bus_net["bus_type"]
            sheet2[XLSX.CellRef(row, 3)] = bus_net["vmax"]
            sheet2[XLSX.CellRef(row, 4)] = bus_net["vmin"]
            # Add solution data
            sheet2[XLSX.CellRef(row, 5)] = round(get(bus_sol, "vm", 0), digits=4)
            sheet2[XLSX.CellRef(row, 6)] = round(get(bus_sol, "va", 0), digits=4)
            sheet2[XLSX.CellRef(row, 7)] = round(rad2deg(get(bus_sol, "va", 0)), digits=4)

            row += 1
        end

        # Sheet 3: Generator data
        sheet3 = XLSX.addsheet!(xf, "generators")

        # Gen sheet headers
        gen_headers = ["bus number", "status", "pmax", "base MVA", "cost", "qg", "pg", "pg_cost"]

        # Write gen headers
        for (i, header) in enumerate(gen_headers)
            sheet3[XLSX.CellRef(1, i)] = header
        end

        # Write gen data
        row = 2
        sorted_gens = sort(collect(result["solution"]["gen"]), by=x -> (network_data["gen"][x[1]]["gen_bus"], network_data["gen"][x[1]]["source_id"][3]))
        for (gen_id, gen_sol) in sorted_gens
            gen_net = network_data["gen"][gen_id]

            sheet3[XLSX.CellRef(row, 1)] = gen_net["gen_bus"]
            sheet3[XLSX.CellRef(row, 2)] = gen_net["gen_status"]
            sheet3[XLSX.CellRef(row, 3)] = gen_net["pmax"]
            sheet3[XLSX.CellRef(row, 4)] = gen_net["mbase"]
            sheet3[XLSX.CellRef(row, 5)] = gen_net["cost"][1]  # First item of cost array
            # Add solution data
            sheet3[XLSX.CellRef(row, 6)] = round(get(gen_sol, "qg", 0), digits=4)
            sheet3[XLSX.CellRef(row, 7)] = round(get(gen_sol, "pg", 0), digits=4)
            sheet3[XLSX.CellRef(row, 8)] = round(get(gen_sol, "pg_cost", 0), digits=4)

            row += 1
        end        # Sheet 3: Branch data

        sheet4 = XLSX.addsheet!(xf, "branches")

        # Branch sheet headers
        branch_headers = ["id", "from bus", "to bus", "transformer", "status", "x", "r", "b from", "b to", "pf", "pt", "p loss", "qt", "qf", "q loss", "p loss expected", "q loss expected", "p loss mismatch", "q loss mismatch"]

        # Write branch headers
        for (i, header) in enumerate(branch_headers)
            sheet4[XLSX.CellRef(1, i)] = header
        end        # Write branch data
        row = 2
        # Sort branches by (from bus, to bus)
        sorted_branches = sort(collect(result["solution"]["branch"]),
            by=x -> (network_data["branch"][x[1]]["f_bus"],
                network_data["branch"][x[1]]["t_bus"]))
        for (branch_id, branch_sol) in sorted_branches
            branch_net = network_data["branch"][branch_id]
            f_bus = branch_net["f_bus"]
            t_bus = branch_net["t_bus"]

            sheet4[XLSX.CellRef(row, 1)] = branch_id
            sheet4[XLSX.CellRef(row, 2)] = f_bus
            sheet4[XLSX.CellRef(row, 3)] = t_bus
            sheet4[XLSX.CellRef(row, 4)] = branch_net["transformer"]
            sheet4[XLSX.CellRef(row, 5)] = branch_net["br_status"]
            sheet4[XLSX.CellRef(row, 6)] = branch_net["br_x"]
            sheet4[XLSX.CellRef(row, 7)] = branch_net["br_r"]
            sheet4[XLSX.CellRef(row, 8)] = branch_net["b_fr"]
            sheet4[XLSX.CellRef(row, 9)] = branch_net["b_to"]            # Add solution data
            pt = get(branch_sol, "pt", 0)
            pf = get(branch_sol, "pf", 0)
            qt = get(branch_sol, "qt", 0)
            qf = get(branch_sol, "qf", 0)
            p_loss = pf + pt
            q_loss = qf + qt
            sheet4[XLSX.CellRef(row, 10)] = round(pf, digits=4)
            sheet4[XLSX.CellRef(row, 11)] = round(pt, digits=4)
            sheet4[XLSX.CellRef(row, 12)] = round(p_loss, digits=4)
            sheet4[XLSX.CellRef(row, 13)] = round(qt, digits=4)
            sheet4[XLSX.CellRef(row, 14)] = round(qf, digits=4)
            sheet4[XLSX.CellRef(row, 15)] = round(q_loss, digits=4)
            expected_flow = power_flow(
                result["solution"]["bus"]["$f_bus"]["vm"], result["solution"]["bus"]["$f_bus"]["va"],
                result["solution"]["bus"]["$t_bus"]["vm"], result["solution"]["bus"]["$t_bus"]["va"],
                branch_net["br_r"], branch_net["br_x"],  # r, x
                branch_net["b_fr"], branch_net["b_to"]   # b_from, b_to (each already per-end)
            )
            expected_p_loss = expected_flow["Loss_P"]
            expected_q_loss = expected_flow["Loss_Q"]
            sheet4[XLSX.CellRef(row, 16)] = round(expected_p_loss, digits=4)
            sheet4[XLSX.CellRef(row, 17)] = round(expected_q_loss, digits=4)
            p_loss_mismatch = p_loss - expected_p_loss
            q_loss_mismatch = q_loss - expected_q_loss
            sheet4[XLSX.CellRef(row, 18)] = round(p_loss_mismatch, digits=4)
            sheet4[XLSX.CellRef(row, 19)] = round(q_loss_mismatch, digits=4)

            row += 1
        end

        # Sheet 5: Load data
        sheet5 = XLSX.addsheet!(xf, "loads")

        # Check if load solution data exists
        has_load_solution = haskey(result["solution"], "load")

        # Load sheet headers
        if has_load_solution
            load_headers = ["load id", "bus number", "pd", "qd", "served (%)", "p", "q"]
        else
            load_headers = ["load id", "bus number", "pd", "qd"]
        end

        # Write load headers
        for (i, header) in enumerate(load_headers)
            sheet5[XLSX.CellRef(1, i)] = header
        end

        # Write load data
        row = 2
        sorted_loads = sort(collect(network_data["load"]), by=x -> parse(Int, x[1]))
        for (load_id, load_net) in sorted_loads
            sheet5[XLSX.CellRef(row, 1)] = load_id
            sheet5[XLSX.CellRef(row, 2)] = load_net["load_bus"]
            sheet5[XLSX.CellRef(row, 3)] = load_net["pd"]
            sheet5[XLSX.CellRef(row, 4)] = load_net["qd"]

            # Add solution data if available
            if has_load_solution && haskey(result["solution"]["load"], load_id)
                load_sol = result["solution"]["load"][load_id]
                sheet5[XLSX.CellRef(row, 5)] = round(get(load_sol, "status", 0) * 100, digits=4)
                sheet5[XLSX.CellRef(row, 6)] = round(get(load_sol, "pd", 0), digits=4)
                sheet5[XLSX.CellRef(row, 7)] = round(get(load_sol, "qd", 0), digits=4)
            end

            row += 1
        end

        # Conditional PowerWorld sheet
        if powerworld
            base_mva = network_data["baseMVA"]
            sheet6 = XLSX.addsheet!(xf, "pw_gen")

            sheet6[XLSX.CellRef(1, 1)] = "Gen"

            pw_headers = ["Number of Bus", "ID", "Gen MW", "Gen Mvar"]
            for (i, header) in enumerate(pw_headers)
                sheet6[XLSX.CellRef(2, i)] = header
            end

            row = 3
            sorted_gens = sort(collect(result["solution"]["gen"]), by=x -> (network_data["gen"][x[1]]["gen_bus"], network_data["gen"][x[1]]["source_id"][3]))
            for (gen_id, gen_sol) in sorted_gens
                gen_net = network_data["gen"][gen_id]

                sheet6[XLSX.CellRef(row, 1)] = gen_net["gen_bus"]
                sheet6[XLSX.CellRef(row, 2)] = gen_net["source_id"][3]
                sheet6[XLSX.CellRef(row, 3)] = round(get(gen_sol, "pg", 0) * base_mva, digits=2)
                sheet6[XLSX.CellRef(row, 4)] = round(get(gen_sol, "qg", 0) * base_mva, digits=2)

                row += 1
            end

            sheet7 = XLSX.addsheet!(xf, "pw_bus")
            sheet7[XLSX.CellRef(1, 1)] = "Bus"

            # Second row: headers
            bus_pw_headers = ["Number", "PU Volt", "Angle (Deg)"]
            for (i, header) in enumerate(bus_pw_headers)
                sheet7[XLSX.CellRef(2, i)] = header
            end

            # Write bus data
            row = 3
            sorted_buses = sort(collect(result["solution"]["bus"]), by=x -> parse(Int, x[1]))
            for (bus_id, bus_sol) in sorted_buses
                sheet7[XLSX.CellRef(row, 1)] = parse(Int, bus_id)
                sheet7[XLSX.CellRef(row, 2)] = round(get(bus_sol, "vm", 0), digits=5)
                sheet7[XLSX.CellRef(row, 3)] = round(rad2deg(get(bus_sol, "va", 0)), digits=2)
                row += 1
            end

            # PowerWorld Branch sheet
            sheet8 = XLSX.addsheet!(xf, "pw_branch")

            # First row: "Branch" in first column only
            sheet8[XLSX.CellRef(1, 1)] = "Branch"

            # Second row: headers
            branch_pw_headers = ["From Number", "To Number", "Circuit", "MW From", "MW To", "Mvar From", "Mvar To"]
            for (i, header) in enumerate(branch_pw_headers)
                sheet8[XLSX.CellRef(2, i)] = header
            end

            # Write branch data
            row = 3
            # Sort branches by (from bus, to bus)
            sorted_branches = sort(collect(result["solution"]["branch"]),
                by=x -> (network_data["branch"][x[1]]["f_bus"],
                    network_data["branch"][x[1]]["t_bus"]))
            for (branch_id, branch_sol) in sorted_branches
                branch_net = network_data["branch"][branch_id]

                sheet8[XLSX.CellRef(row, 1)] = branch_net["f_bus"]
                sheet8[XLSX.CellRef(row, 2)] = branch_net["t_bus"]
                sheet8[XLSX.CellRef(row, 3)] = "1"
                sheet8[XLSX.CellRef(row, 4)] = round(get(branch_sol, "pf", 0) * base_mva, digits=3)
                sheet8[XLSX.CellRef(row, 5)] = round(get(branch_sol, "pt", 0) * base_mva, digits=3)
                sheet8[XLSX.CellRef(row, 6)] = round(get(branch_sol, "qf", 0) * base_mva, digits=3)
                sheet8[XLSX.CellRef(row, 7)] = round(get(branch_sol, "qt", 0) * base_mva, digits=3)

                row += 1
            end

            # PowerWorld Load sheet
            sheet9 = XLSX.addsheet!(xf, "pw_load")

            # First row: "Load" in first column only
            sheet9[XLSX.CellRef(1, 1)] = "Load"

            # Second row: headers
            load_pw_headers = ["Number of Bus", "ID", "MW", "Mvar"]
            for (i, header) in enumerate(load_pw_headers)
                sheet9[XLSX.CellRef(2, i)] = header
            end

            # Write load data only if solution contains load data
            if has_load_solution
                row = 3
                sorted_loads = sort(collect(result["solution"]["load"]), by=x -> parse(Int, x[1]))
                for (load_id, load_sol) in sorted_loads
                    load_net = network_data["load"][load_id]

                    sheet9[XLSX.CellRef(row, 1)] = load_net["load_bus"]
                    sheet9[XLSX.CellRef(row, 2)] = "1"
                    sheet9[XLSX.CellRef(row, 3)] = round(get(load_sol, "pd", 0) * base_mva, digits=3)
                    sheet9[XLSX.CellRef(row, 4)] = round(get(load_sol, "qd", 0) * base_mva, digits=3)

                    row += 1
                end
            end
        end
    end

end