configfile: "config.yaml"

rule search:
    output:
        db = "{session}/session.db"
    shell:
        "protein-detective search --taxon-id 9606 --reviewed --subcellular-location-uniprot nucleus --subcellular-location-go GO:0005634 --molecular-function-go GO:0003677 --limit 100 {session}"

rule retrieve:
    input:
        db = "{session}/session.db"
    output:
        downloads=directory(f"{SESSION}/downloads")
    shell:
        "protein-detective retrieve {session}"

rule filter:
    input:
        downloads=directory(f"{SESSION}/downloads")
    output:
        filtered=directory(f"{SESSION}/filtered")
    shell:
        "protein-detective filter --confidence-threshold 50 --min-residues 100 --max-residues 1000 {session} && touch {output}"

rule powerfit_run:
    input:
        filtered=directory(f"{SESSION}/filtered")
    output:
        touch("{session}/powerfit/.done")
    shell:
        "protein-detective powerfit run {session}/powerfit/ribosome-KsgA.map 13 {session} && touch {output}"

rule powerfit_report:
    input:
        done = "{session}/powerfit/.done"
    output:
        report = "{session}/powerfit_report.txt"
    shell:
        "protein-detective powerfit report {session} > {output.report}"

rule powerfit_fit_models:
    input:
        report = "{session}/powerfit_report.txt"
    output:
        touch("{session}/powerfit_fit_models/.done")
    shell:
        "protein-detective powerfit fit-models {session} && touch {output}"

