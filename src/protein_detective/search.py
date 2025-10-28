"""Module with search logic."""

import logging
from dataclasses import dataclass, field

from protein_quest.uniprot import Query, search4macromolecular_complexes

logger = logging.getLogger(__name__)


@dataclass
class UniprotQuery(Query):
    """A UniProt search query with interaction partner options and pdb residue length filters.

    Parameters:
        interaction_partner_seeds: A set of UniProt accessions to search for interaction partners.
        interaction_partners_excludes: A set of UniProt accessions to exclude from interaction partner results.
    """

    interaction_partner_seeds: set[str] = field(default_factory=set)
    interaction_partner_excludes: set[str] = field(default_factory=set)
    min_residues: int | None = None
    max_residues: int | None = None


def search_for_interaction_partners(query: UniprotQuery, limit: int) -> set[str]:
    """Searches for interaction partners in UniProt database and ComplexPortal.

    Args:
        query: The search query containing seeds and excludes.
        limit: The maximum number of results to return from the database query.

    Returns:
        A set of unique UniProt accessions of interaction partners found.
    """
    if not query.interaction_partner_seeds:
        logger.info("No interaction partner seeds provided; skipping search for interaction partners.")
        return set()
    logger.info("Searching for interaction partners of seeds %s", query.interaction_partner_seeds)
    uniprot_accessions_of_partners: set[str] = set()

    complexes = search4macromolecular_complexes(query.interaction_partner_seeds, limit)
    for complex_entry in complexes:
        uniprot_accessions_of_partners.update(complex_entry.members)

    # Exclude seeds and excludes from results
    uniprot_accessions_of_partners.difference_update(query.interaction_partner_seeds)
    uniprot_accessions_of_partners.difference_update(query.interaction_partner_excludes)

    logger.info(
        "Found %d unique interaction partners in %d macromolecular complexes after excluding %d accessions",
        len(uniprot_accessions_of_partners),
        len(complexes),
        len(query.interaction_partner_excludes),
    )
    return uniprot_accessions_of_partners
