CREATE VIEW OR REPLACE solutions AS
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
ORDER BY cc DESC, rank ASC;