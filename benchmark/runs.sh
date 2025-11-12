#!/usr/bin/bash

# Submit with : sbatch runs.sh

#SBATCH --nodes=1
#SBATCH --ntasks-per-node=1
#SBATCH --cpus-per-task=16
#SBATCH --partition=medium

# Make progressbar less chatty
export TQDM_MININTERVAL=9

. ../.venv/bin/activate
find work -name run.sh -execdir bash {} \;
