# CUCKOO CORE

![CUCKOO CORE header](https://github.com/user-attachments/assets/056b0512-4708-4bc7-8331-1a4cf728caa1)

CUCKOO CORE is a research-oriented Django implementation of the task-scheduling and service-cache optimization framework presented in **“Cuckoo Search-Enabled Task Scheduling and Cache Updating in Vehicular Edge-Fog Computing.”**

The repository focuses on reproducing the paper's system model, optimization workflow, and experimental benchmarks for vehicular edge–fog computing. It supports dependency-aware application scheduling, local/V2V/V2I execution, service-cache decisions, and reproducible evaluation of the resulting schedules.

> This is an independent research implementation and is not the official source-code repository of the paper's authors.

## Research Scope

The implementation includes:

- DAG-based modeling of dependent application tasks;
- local, vehicle-to-vehicle, and vehicle-to-infrastructure execution;
- task ranking and dependency-aware scheduling;
- joint task-assignment and service-cache optimization;
- continuous resource allocation for CPU frequency and transmission power;
- the paper's cuckoo-search-based DCSGA workflow;
- paper baselines and ablation configurations;
- benchmark generation for Figures 6–10;
- seeded runs and exportable CSV, JSON, PNG, and PDF results.

Additional experimental optimization work is maintained separately until its accompanying research is ready for publication.

## Requirements

- Python 3.13 (tested with Python 3.13.7)
- PostgreSQL
- Docker and Docker Compose

Creating a virtual environment is recommended.

## Installation

### 1. Clone the repository

```bash
git clone https://github.com/cuckoo-heuristic/cuckoo-core.git
cd cuckoo-core
```

### 2. Create and activate a virtual environment

Windows:

```powershell
py -3.13 -m venv .venv
.venv\Scripts\activate
```

Linux or macOS:

```bash
python3.13 -m venv .venv
source .venv/bin/activate
```

### 3. Install dependencies

```bash
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### 4. Configure the environment

Copy `.env.example` to `.env`, then replace the example values with your local Django and PostgreSQL settings.

```bash
cp .env.example .env
```

Do not commit `.env`, database passwords, or production secret keys.

### 5. Start the database services

```bash
docker compose up -d
```

### 6. Apply migrations

```bash
python manage.py migrate
```

### 7. Run the development server

```bash
python manage.py runserver
```

The API documentation is then available at:

- Swagger UI: `http://127.0.0.1:8000/api/docs/swagger/`
- ReDoc: `http://127.0.0.1:8000/api/docs/redoc/`

## Benchmarking

The project provides separate execution paths for simulation and isolated benchmarking. Stop the live simulation before starting a benchmark so that worker activity does not modify the benchmark state.

The paper-oriented benchmark endpoint is:

```text
POST /run/paper-benchmark/
```

The benchmark framework records the random seed, scenario configuration, stopping rule, runtime, and objective-evaluation count. Paper-reproduction results and later optimizer comparisons should be reported separately because equal generations do not necessarily represent equal computational effort.

## Project Structure

```text
algorithm/       DCSGA, resource-allocation procedures, cache updating, and paper methods
application/     Application data and API layer
cache/           Service-cache models and API layer
cuckoo_core/     Django project configuration
dag/             Task graphs and dependency models
execution/       Task-execution records
object/          Vehicles, RSUs, and service-provider models
parameter/       Simulation and optimization parameters
resource/        Computing-resource models
run/             Workers, simulation services, benchmarks, and result export
state/           Runtime state models
system/          Shared context-building and reset utilities
```

## Reproducibility Notes

- Use fixed seeds for repeatable scenarios.
- Record the population size, stopping rule, and objective-evaluation budget with every result.
- Do not compare population-based optimizers only by generation count.
- Use multiple independent seeds for final statistical comparisons.
- Keep paper-reproduction experiments separate from diagnostic or extended experiments.
- Database contents and reconstructed DAGs must be documented with the reported results.

## Reference

If this implementation supports your research, cite the source paper:

> **Cuckoo Search-Enabled Task Scheduling and Cache Updating in Vehicular Edge-Fog Computing.** IEEE Transactions on Vehicular Technology, 2025. DOI: [10.1109/TVT.2025.3540639](https://doi.org/10.1109/TVT.2025.3540639)

## Acknowledgments

Special thanks to Fateme Ghaderi for her support and contributions to the project.

## License

This project is available under the [MIT License](LICENSE).

