## CUCKOO CORE
![CUCKOO CORE - Headder](https://github.com/user-attachments/assets/c30c5a48-8e34-4736-a26e-3bcbe1840e68)

## Usage
**Requirements:** `python` 3.13.7 or higher ( *Recommendation: Create a Virtual Environment* )

1: Install Required Libraries
```bash
pip install -r requirements.txt
```

2: Environment

Change `.env.example` to `.env` and replace the example values with your own configuration values.

3: Run Docker Containers
```bash
docker compose up -d
```

4: Apply Migrations
```bash
python manage.py migrate
```

5: Run Django
```bash
python manage.py runserver
```

## Acknowledgments
### Special Thanks:
Fateme Ghaderi

### Papers:
[Cuckoo Search-Enabled Task Scheduling and Cache Updating in Vehicular Edge-Fog Computing](https://ieeexplore.ieee.org/document/10879579)
[Performance Optimization of Task Scheduling in Fog and Edge Computing using meta-heuristic algorithms for IoT Networks](https://norma.ncirl.ie/7043/)

