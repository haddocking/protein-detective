from pathlib import Path

from powerfit_em.powerfit import powerfit

# TODO make run in parallel/distributed instead of sequentially
# with some distributed computing framework such as
# multiprocessing, joblib, dask, snakemake, airflow, cwl, prefect, ray, asyncio-subprocess

# TODO make run available as a command line tool


def run():
    # TODO read files from arguments, instead of hardcoding example values
    # TODO when given gpu=None arg then also call powerfit with gpu=None
    nr_devices = 4
    device_id = 0  # This would be set dynamically in a real batch job
    pdb_files = ["bla.pdb"]
    with Path("density_map.mrc").open("rb") as density_map:
        for pdb_file in pdb_files:
            with Path(pdb_file).open() as template_structure:
                powerfit(
                    target_volume=density_map,
                    resolution=20,
                    template_structure=template_structure,
                    gpu=f"0:{device_id}",
                    directory=str(Path("out") / Path(pdb_file).name),
                )
            device_id = (device_id + 1) % nr_devices
