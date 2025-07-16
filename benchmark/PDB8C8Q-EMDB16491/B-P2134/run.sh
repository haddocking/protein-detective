#!/bin/sh

wget https://ftp.ebi.ac.uk/pub/databases/emdb/structures/EMD-16491/map/emd_16491.map.gz
gunzip emd_16491.map.gz

protein-detective search \
    --taxon-id 284812 \
    --subcellular-location-uniprot "Mitochondrion inner membrane" \
    --subcellular-location-go GO:0005743 \
    --limit 50000 \
    .
# Search completed: 184 UniProt entries found, 9 PDBe structures, 40 UniProt to PDB mappings, 180 AlphaFold structures.

protein-detective retrieve .
# Structures retrieved successfully: 9 PDBe structures, 180 AlphaFold structures downloaded to downloads

# Is fitted model 8C8Q:B part of the search results?
ls -1 downloads/8c8q.cif 
# downloads/8c8q.cif
# Yes it is

# Get length known B chain
python3 -c "import atomium; print(atomium.open('downloads/8c8q.cif').model.chain('B').length)"
# 238
# use 200 to 280 as residue range

protein-detective density-filter \
    --confidence-threshold 70 \
    --min-residues 200 \
    --max-residues 280 \
    .
# Filtered 46 structures, written to density_filtered directory.
# Discarded 134 structures based on density confidence.

# TODO prune
protein-detective prune-pdbs \
    --min-residues 200 \
    --max-residues 280 \
    .

# prep density for just unknown volume
chimerax --nogui --script prep.cxc

# powerfit
# Use vkfft branch of powerfit
protein-detective powerfit run emd_16491-P21534_8c8q_B2A.mrc 3.38 . --gpu
# Took 3 minutes for 54 structures

protein-detective powerfit report .
# Great that 8c8q:B is first
# 15th place is different uniprot

# Write all fitted pdbs
protein-detective powerfit fit-models . --top 100

# View known model + unknown density + fitted models in mol* or chimeraX
