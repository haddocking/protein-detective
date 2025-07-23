# Benchmark

All the protein-detective sub commands can be assembled into a pipeline.
This pipeline can be run on multiple density maps and uniprot queries.
This directory contains a script generators to run the pipeline on multiple things.

The `print-commands.py` script reads rows from "Benchmarklist.csv" file, and for each
row, it creates a directory structure and a corresponding run.sh script
to execute a protein-detective pipeline.

The "Benchmarklist.csv" file is not included in the repository, but you can create your own
by looking in print-commands.py for the expected columns.

Run with

```
python3 print-commands.py
find work -name run.sh -execdir bash {} \; 2>&1 | tee run.log
```
