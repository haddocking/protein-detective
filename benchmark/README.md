# Benchmark

All the protein-detective sub commands can be assembled into a pipeline.
This pipeline can be run on multiple density maps and uniprot queries.
This directory contains a script generators to run the pipeline on multiple things.

The `print-commands.py` script reads rows from "Benchmarklist.csv" file, and for each
row, it creates a directory structure and a corresponding *.sh scripts
to execute a protein-detective pipeline.

* The remote.sh script does search+retrieve as it talks to remote servers and is better to run sequentially.
* The filter.sh script can run in parallel on CPU.
* The powerfit.sh script can be run in parallel on GPU.

The "Benchmarklist.csv" file is not included in the repository, but you can create your own
by looking in print-commands.py for the expected columns.

Run with

```shell
python3 print-commands.py
# Follow the printed instructions to run the generated scripts
```

The other `./*.py` scripts are utility scripts to troubleshoot and analyze the results of the benchmark runs.
