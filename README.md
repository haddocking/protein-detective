# protein-detective

[![Documentation](https://img.shields.io/badge/Documentation-bonvinlab.org-blue?style=flat-square&logo=gitbook)](https://www.bonvinlab.org/protein-detective/)
[![CI](https://github.com/haddocking/protein-detective/actions/workflows/ci.yml/badge.svg)](https://github.com/haddocking/protein-detective/actions/workflows/ci.yml)
[![Research Software Directory Badge](https://img.shields.io/badge/rsd-00a3e3.svg)](https://www.research-software.nl/software/protein-detective)
[![PyPI](https://img.shields.io/pypi/v/protein-detective)](https://pypi.org/project/protein-detective/)
[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.15632658.svg)](https://doi.org/10.5281/zenodo.15632658)

Python package to detect proteins in EM density maps.

It uses

- [Uniprot Sparql endpoint](https://sparql.uniprot.org/) to search for proteins and their measured or predicted 3D structures.
- [powerfit](https://pypi.org/project/powerfit-em/) to fit protein structure in a Electron Microscopy (EM) density map.

An example workflow:

```mermaid
graph LR;
    search{Search UniprotKB} --> |uniprot_accessions|fetchpdbe{Retrieve PDBe}
    search{Search UniprotKB} --> |uniprot_accessions|fetchad{Retrieve AlphaFold}
    fetchpdbe -->|mmcif_files| residuefilter{Filter on nr residues + write chain A}
    fetchad -->|pdb_files| densityfilter{Filter out low confidence}
    residuefilter -->|pdb_files| powerfit
    densityfilter -->|pdb_files| powerfit
    powerfit -->|*/solutions.out| solutions{Best scoring solutions}
    solutions -->|dataframe| fitmodels{Fit models}
```

## Install

```shell
pip install protein-detective
```

Or to use the latest development version:
```
pip install git+https://github.com/haddocking/protein-detective.git
```

## Usage

The main entry point is the `protein-detective` command line tool which has multiple subcommands to perform actions.


To use programmaticly, see the [notebooks](docs/notebooks) and [API documentation](https://www.bonvinlab.org/protein-detective/autoapi/summary/).

### Search Uniprot for structures

```shell
protein-detective search \
    --taxon-id 9606 \
    --reviewed \
    --subcellular-location-uniprot nucleus \
    --subcellular-location-go GO:0005634 \
    --molecular-function-go GO:0003677 \
    --limit 100 \
    ./mysession
```
([GO:0005634](https://www.ebi.ac.uk/QuickGO/term/GO:0005634) is "Nucleus" and [GO:0003677](https://www.ebi.ac.uk/QuickGO/term/GO:0003677) is  "DNA binding")

In `./mysession` directory, you will find session.db file, which is a [DuckDB](https://duckdb.org/) database with search results.

### To retrieve a bunch of structures

```shell
protein-detective retrieve ./mysession
```

In `./mysession` directory, you will find mmCIF files from PDBe and PDB files and AlphaFold DB.

### To filter AlphaFold structures on confidence

Filter AlphaFoldDB structures based on density confidence.
Keeps entries with requested number of residues which have a confidence score above the threshold.
Also writes pdb files with only those residues.

```shell
protein-detective density-filter \
    --confidence-threshold 50 \
    --min-residues 100 \
    --max-residues 1000 \
    ./mysession
```

### To prune PDBe files

Make PDBe files smaller by only keeping first chain of found uniprot entry and renaming to chain A.

```shell
protein-detective prune-pdbs \
    --min-residues 100 \
    --max-residues 1000 \
    ./mysession
```

### Powerfit

Generate the powerfit commands for the filtered and pruned structures.

```shell
protein-detective powerfit commands ../powerfit-tutorial/ribosome-KsgA.map 13 docs/session1
```
This will print commands to the terminal, which you can then run in whatever way you prefer.
Like just sequentially, or with [GNU parallel](https://www.gnu.org/software/parallel/) or as a [Slurm array job](https://slurm.schedmd.com/job_array.html).

Alternatively, you can use the `protein-detective powerfit run ...` command to run powerfit commands sequentially, which is useful for small datasets with rough options.

```shell

To print top 10 solutions to the terminal, you can use:

```shell
protein-detective powerfit report docs/session1
```

Outputs something like:

```
powerfit_run_id,structure,rank,cc,fishz,relz,translation,rotation,pdb_id,pdb_file,uniprot_acc
10,A8MT69_pdb4e45.ent_B2A,1,0.432,0.463,10.091,227.18:242.53:211.83,0.0:1.0:1.0:0.0:0.0:1.0:1.0:0.0:0.0,4E45,docs/session1/single_chain/A8MT69_pdb4e45.ent_B2A.pdb,A8MT69
10,A8MT69_pdb4ne5.ent_B2A,1,0.423,0.452,10.053,227.18:242.53:214.9,0.0:-0.0:-0.0:-0.604:0.797:0.0:0.797:0.604:0.0,4NE5,docs/session1/single_chain/A8MT69_pdb4ne5.ent_B2A.pdb,A8MT69
...
```

To generate model PDB files rotated/translated to PowerFit solutions, you can use:

```shell
protein-detective powerfit fit-models docs/session1
```

## Contributing

For development information and contribution guidelines, please see [CONTRIBUTING.md](CONTRIBUTING.md).
