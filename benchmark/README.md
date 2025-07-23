# Benchmark

The `print-commands.py` script generates run.sh files for benchmarking based on a CSV file.

It reads benchmark data from "Benchmarklist.csv", and for each relevant
row, it creates a directory structure and a corresponding run.sh script
to execute a protein-detective pipeline.

Run with
```
python3 print-commands.py
find work -name run.sh -execdir bash {} \; | tee run.log

```