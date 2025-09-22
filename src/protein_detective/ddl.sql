-- If session_dir is not set, use current working directory
SET VARIABLE session_dir = coalesce(
    getvariable('session_dir'),
    '.'
);

CREATE TABLE IF NOT EXISTS uniprot_searches (
    query JSON,
);

CREATE TABLE IF NOT EXISTS proteins (
    uniprot_acc TEXT PRIMARY KEY,
);

CREATE TABLE IF NOT EXISTS pdbs (
    pdb_id TEXT PRIMARY KEY,
    method TEXT NOT NULL,
    resolution REAL,
    mmcif_file TEXT,
);

-- pdb could have multiple proteins so use many-to-many table
CREATE TABLE IF NOT EXISTS proteins_pdbs (
    uniprot_acc TEXT NOT NULL,
    pdb_id TEXT NOT NULL,
    uniprot_chains TEXT NOT NULL,
    chain TEXT NOT NULL,
    FOREIGN KEY (uniprot_acc) REFERENCES proteins (uniprot_acc),
    FOREIGN KEY (pdb_id) REFERENCES pdbs (pdb_id),
    PRIMARY KEY (uniprot_acc, pdb_id)
);

CREATE TABLE IF NOT EXISTS alphafolds (
    uniprot_acc TEXT PRIMARY KEY,
    summary JSON,
    bcif_file TEXT,
    cif_file TEXT,
    pdb_file TEXT,
    pae_image_file TEXT,
    pae_doc_file TEXT,
    am_annotations_file TEXT,
    am_annotations_hg19_file TEXT,
    am_annotations_hg38_file TEXT,
    FOREIGN KEY (uniprot_acc) REFERENCES proteins (uniprot_acc)
);

CREATE SEQUENCE IF NOT EXISTS id_filters START 1;
CREATE TABLE IF NOT EXISTS filters (
    filter_id INTEGER DEFAULT nextval('id_filters') PRIMARY KEY,
    filter_options JSON NOT NULL, -- stores allowed nr residues range
    created_on TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (filter_options)
);

CREATE TABLE IF NOT EXISTS filtered_structures (
    filter_id INTEGER NOT NULL,
    uniprot_acc TEXT NOT NULL, 
    pdb_id TEXT,
    filter_stats JSON NOT NULL,
    passed BOOLEAN,
    output_file TEXT,
    -- PRIMARY KEY (filter_id, uniprot_acc, pdb_id), #-- pdb_id can be NULL so cannot use as part of primary key
    FOREIGN KEY (filter_id) REFERENCES filters (filter_id),
    FOREIGN KEY (uniprot_acc) REFERENCES alphafolds (uniprot_acc),
    FOREIGN KEY (uniprot_acc, pdb_id) REFERENCES proteins_pdbs (uniprot_acc, pdb_id),
);

CREATE SEQUENCE IF NOT EXISTS id_powerfit_runs START 1;
CREATE TABLE IF NOT EXISTS powerfit_runs (
    powerfit_run_id INTEGER DEFAULT nextval('id_powerfit_runs') PRIMARY KEY,
    options JSON NOT NULL,
    UNIQUE (options)
);

-- Need to use view, when using table then new runs will not be picked up by read_csv
CREATE VIEW IF NOT EXISTS raw_solutions AS
SELECT
    parse_path(filename)[-3] AS powerfit_run_id,
    parse_path(filename)[-2] AS structure,
    rank, cc, fishz, relz,
    [x,y,z]::FLOAT[3] AS translation,
    [a11, a12, a13, a21, a22, a23, a31, a32, a33]::FLOAT[9] AS rotation,
FROM
    read_csv(
        getvariable('session_dir') || '/powerfit/*/*/solutions.out',
        filename=True, normalize_names=True,
        -- Need to specify types as powerfit/0/dummy/solutions.out only has header
        -- and sniffer_csv will type columns as VARCHAR
        columns={
            'rank': 'INTEGER',
            'cc': 'FLOAT',
            'fishz': 'FLOAT',
            'relz': 'FLOAT',
            'x': 'FLOAT',
            'y': 'FLOAT',
            'z': 'FLOAT',
            'a11': 'FLOAT',
            'a12': 'FLOAT',
            'a13': 'FLOAT',
            'a21': 'FLOAT',
            'a22': 'FLOAT',
            'a23': 'FLOAT',
            'a31': 'FLOAT',
            'a32': 'FLOAT',
            'a33': 'FLOAT',
        }
    )
;

CREATE VIEW IF NOT EXISTS solutions AS
SELECT
    powerfit_run_id,
    structure,
    rank,
    cc,
    fishz,
    relz,
    translation,
    rotation,
    concat_ws('/', getvariable('session_dir'), output_file) AS pdb_file,
    uniprot_acc,
    pdb_id
FROM raw_solutions
LEFT JOIN (
    SELECT output_file, uniprot_acc, pdb_id, parse_filename(output_file, true) AS structure
    FROM filtered_structures WHERE output_file IS NOT NULL
) AS a USING (structure)
ORDER BY cc DESC;

CREATE TABLE IF NOT EXISTS raw_fitted_models (
    powerfit_run_id INTEGER NOT NULL,
    structure TEXT NOT NULL,
    rank INTEGER NOT NULL,
    -- unfitted_model_file is foreign key of filtererd_structures.output_file
    unfitted_model_file TEXT NOT NULL,
    fitted_model_file TEXT PRIMARY KEY,
);

CREATE VIEW IF NOT EXISTS fitted_models AS
SELECT
    powerfit_run_id,
    structure,
    rank,
    concat_ws(
        '/',
        getvariable('session_dir'),
        unfitted_model_file
    ) AS unfitted_model_file,
    concat_ws(
        '/',
        getvariable('session_dir'),
        fitted_model_file
    ) AS fitted_model_file
FROM raw_fitted_models;
