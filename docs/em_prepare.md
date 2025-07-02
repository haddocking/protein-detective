# Prepare Electron Microscopy Data

The powerfit program requires a EM density of a unknown structure where it can fit structures into.

Most of the the EM density contains multiple structures, so we want to remove all but the unknown structure.

In this example we will use the [phenix software](https://www.phenix-online.org/) to prepare the EM density.
Make sure you have phenix installed.

For this example we will use [EMD-33292](https://www.ebi.ac.uk/emdb/EMD-33292), a sodium channel, with fitted model [7xm9](https://www.ebi.ac.uk/pdbe/entry/pdb/7xm9).

TODO convert to notebook so we can use Mol* to visualize the EM density and fitted model.