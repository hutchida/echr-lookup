"""10 hand-written test queries -> acceptable expected snapshot documents (HUDOC item ids).

Written from general knowledge of the cases, deliberately *not* copied from the judgment text.
Where several snapshot cases genuinely answer the question, all are accepted.
"""

QUERIES: list[tuple[str, set[str]]] = [
    (
        "Would extraditing a young German man to Virginia, where he faces the death penalty and years on death row, breach the ban on inhuman treatment?",
        {"001-57619"},
    ),
    (
        "Is it lawful to deport a foreign national convicted of serious crimes who has lived in Britain since childhood, when he invokes his family life?",
        {
            "001-176931",
            "001-108113",
            "001-110271",
            "001-91286",
            "001-90402",
            "001-95777",
            "001-106282",
            "001-96587",
            "001-205796",
            "001-219755",
        },
    ),
    (
        "Does a blanket ban on convicted prisoners voting in elections violate the right to free elections?",
        {"001-70442", "001-225312"},
    ),
    (
        "Can the state deport a suspected terrorist to Jordan if there is a risk that evidence obtained by torture will be used at his trial?",
        {"001-108629"},
    ),
    (
        "Removal of a man with advanced AIDS to the Caribbean island where he would lack medical treatment and family support",
        {"001-58035", "001-86490"},
    ),
    (
        "Prisoners sentenced to life imprisonment with no possibility of review or release",
        {"001-122664"},
    ),
    ("Keeping DNA profiles and fingerprints of people who were never convicted", {"001-90051"}),
    (
        "Were Iraqi civilians killed by British soldiers within the United Kingdom's jurisdiction, and did the state investigate the deaths?",
        {"001-105606"},
    ),
    (
        "Risk to returned asylum seekers from indiscriminate violence and famine in Mogadishu",
        {"001-105434"},
    ),
    (
        "Detaining an asylum seeker at a reception centre while his claim is processed: is that lawful detention to prevent unauthorised entry?",
        {"001-84709"},
    ),
]
