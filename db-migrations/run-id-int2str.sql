CREATE TABLE powerfit_runs_new (
    powerfit_run_id TEXT PRIMARY KEY,
    options JSON NOT NULL,
    UNIQUE (options)
);

INSERT INTO powerfit_runs_new (powerfit_run_id, options)
SELECT CAST(powerfit_run_id AS TEXT), options
FROM powerfit_runs;
DROP TABLE powerfit_runs;
ALTER TABLE powerfit_runs_new RENAME TO powerfit_runs;

CREATE TABLE raw_fitted_models_new (
    powerfit_run_id TEXT NOT NULL,
    structure TEXT NOT NULL,
    rank INTEGER NOT NULL,
    unfitted_model_file TEXT NOT NULL,
    fitted_model_file TEXT PRIMARY KEY
);
INSERT INTO raw_fitted_models_new (
    powerfit_run_id,
    structure,
    rank,
    unfitted_model_file,
    fitted_model_file
)
SELECT
    CAST(powerfit_run_id AS TEXT),
    structure,
    rank,
    unfitted_model_file,
    fitted_model_file
FROM raw_fitted_models;

DROP TABLE raw_fitted_models;
ALTER TABLE raw_fitted_models_new RENAME TO raw_fitted_models;