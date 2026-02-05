# Islanding Operation & Dynamic Simulation Project

This repository is a modified fork of [PowerModels.jl](https://github.com/lanl-ansi/PowerModels.jl), customized for power system islanding optimization and dynamic validation using Siemens PSS®E.

The workflow optimizes network separation (islanding) using Julia/PowerModels and validates the stability of the result using PSS®E dynamic simulation (Python).

## Prerequisites

Before running the simulation, ensure your system meets the following requirements:

*   **Operating System:** Windows (Required for PSS®E)
*   **PSS®E:** Version 36 (36.1 recommended)
*   **Python:** Version 3.11 (Exact version required for PSS®E 36 compatibility)
*   **Julia:** Latest stable version

## Installation & Setup

### 1. Fetch the Code
Clone the repository and switch to the `islanding` branch (if not already there):

```bash
git clone https://github.com/THEMRN/PowerModels.jl.git
cd PowerModels.jl
git checkout islanding
```

### 2. Configure Python Environment
The simulation script requires specific Python libraries. Ensure you are using **Python 3.11**.

Install the required packages:

```bash
pip install pandas plotly xlsxwriter openpyxl
```

### 3. Configure PSS®E Path
You must point the simulation script to your local PSS®E installation.

1.  Open the file `runners/psse_scripts/dynamic.py` in your editor.
2.  Locate the `PSSE_PATH` variable (approx. line 15).
3.  Update the path to match your system's PSS®E installation directory.

    ```python
    # Example configuration:
    PSSE_PATH = r"C:\Program Files\PTI\PSSE36\36.1"
    ```

### 4. Configure Julia Environment
Initialize the Julia project and install dependencies.

Open a terminal in the project root (`PowerModels.jl/`) and run:
```bash
julia --project=. -e "using Pkg; Pkg.instantiate(); Pkg.add(\"Ipopt\")"
```
*Note: `Ipopt` is required for the optimization solver but may not be in the default dependencies list.*

## Usage

The main entry point for the workflow is the `runners/islanding.jl` script.

1.  Open `runners/islanding.jl` to review configuration settings (e.g., target cases, objective functions).
2.  Run the islanding simulation:

```bash
julia --project=. runners/islanding.jl
```

### What This Script Does
1.  **Optimization:** Uses PowerModels.jl to determine optimal generation dispatch and load shedding for the islanded network.
2.  **Report Generation:** Creates detailed Excel reports of the steady-state solution.
3.  **Dynamic Simulation:** Automatically calls `runners/psse_scripts/dynamic.py` to:
    *   Load the case in PSS®E.
    *   Perform dynamic stability simulation (e.g., line tripping).
    *   Plot results (Frequency, Voltage, etc.) using Plotly.

## Project Structure

*   **`src/`**: Core PowerModels.jl source code (modified).
*   **`runners/`**: Custom scripts for this project.
    *   `islanding.jl`: Main driver script.
    *   `psse_scripts/dynamic.py`: Python driver for PSS®E.
*   **`cases/`**: Network data files (matpower/psse).
