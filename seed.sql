BEGIN;

-- 1) ApplicationType
INSERT INTO dag_applicationtype (name, deadline, description, initial_snapshot)
VALUES
('app_type_30ms',  30,  'Tddl_n=30ms', NULL),
('app_type_40ms',  40,  'Tddl_n=40ms', NULL),
('app_type_50ms',  50,  'Tddl_n=50ms', NULL),
('app_type_60ms',  60,  'Tddl_n=60ms', NULL),
('app_type_70ms',  70,  'Tddl_n=70ms', NULL),
('app_type_80ms',  80,  'Tddl_n=80ms', NULL),
('app_type_90ms',  90,  'Tddl_n=90ms', NULL),
('app_type_100ms', 100, 'Tddl_n=100ms', NULL)
ON CONFLICT DO NOTHING;

-- 2) TaskType
INSERT INTO dag_tasktype (name, description, size, initial_snapshot)
VALUES
('tt_100kb', 'Dn,ij=100kb', 12500, NULL),
('tt_120kb', 'Dn,ij=120kb', 15000, NULL),
('tt_140kb', 'Dn,ij=140kb', 17500, NULL),
('tt_160kb', 'Dn,ij=160kb', 20000, NULL),
('tt_180kb', 'Dn,ij=180kb', 22500, NULL),
('tt_200kb', 'Dn,ij=200kb', 25000, NULL),
('tt_220kb', 'Dn,ij=220kb', 27500, NULL),
('tt_240kb', 'Dn,ij=240kb', 30000, NULL),
('tt_260kb', 'Dn,ij=260kb', 32500, NULL),
('tt_300kb', 'Dn,ij=300kb', 37500, NULL)
ON CONFLICT (name) DO NOTHING;

-- 3) Tasks
WITH
apps AS (SELECT id, name FROM dag_applicationtype),
tt AS (SELECT id, name FROM dag_tasktype),
task_data AS (SELECT * FROM (VALUES
    (1, 'T1',  10000000, 'tt_100kb'), (2, 'T2',  12000000, 'tt_120kb'),
    (3, 'T3',  14000000, 'tt_140kb'), (4, 'T4',  16000000, 'tt_160kb'),
    (5, 'T5',  18000000, 'tt_180kb'), (6, 'T6',  20000000, 'tt_200kb'),
    (7, 'T7',  22000000, 'tt_220kb'), (8, 'T8',  24000000, 'tt_240kb'),
    (9, 'T9',  26000000, 'tt_260kb'), (10,'T10', 30000000, 'tt_300kb')
) AS v(ord, idx, cycles, tt_name))
INSERT INTO dag_task ("index", workload_cycles, initial_snapshot, application_type_id_id, task_type_id_id)
SELECT d.idx, d.cycles, NULL, a.id, t.id
FROM task_data d, apps a, tt t
WHERE t.name = d.tt_name;

-- 4) Dependencies
WITH task_map AS (
  SELECT t.id, t.index, t.application_type_id_id 
  FROM dag_task t
)
INSERT INTO dag_taskdependency (initial_snapshot, child_task_id_id, parent_task_id_id)
SELECT NULL, c.id, p.id
FROM task_map p
JOIN task_map c ON p.application_type_id_id = c.application_type_id_id
JOIN (VALUES
    ('T1','T2'), ('T1','T3'), ('T2','T4'), ('T2','T5'),
    ('T3','T5'), ('T3','T6'), ('T4','T7'), ('T5','T7'),
    ('T5','T8'), ('T6','T8'), ('T7','T9'), ('T8','T10')
) AS e(p_idx, c_idx) ON p.index = e.p_idx AND c.index = e.c_idx;

COMMIT;
