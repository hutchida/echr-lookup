"""The curated snapshot choice (HUDOC item IDs) and why each is in. Throwaway build input.

Every ID was confirmed against HUDOC metadata (itemid, appno, date, article, conclusion) from the
UK dump in data/raw/g0b/uk_eng.json, never from memory.
"""

# id -> why it is in the snapshot (demo step / eval theme)
JUDGMENTS = {
    # --- Article 3 expulsion / extradition ---
    "001-57619": "Soering: the founding Art 3 extradition case (death-row phenomenon). Violation. Demo: citing 001-57619§88.",
    "001-58004": "Chahal: Art 3 bars deportation even for national-security threats. Violation. GC.",
    "001-57713": "Vilvarajah: Art 3 asylum expulsion to Sri Lanka. No violation (contrast with Chahal).",
    "001-58035": "D v UK: Art 3 and removal of a terminally ill man. Violation.",
    "001-86490": "N v UK: Art 3 medical-case threshold, removal to Uganda. No violation. GC.",
    "001-59206": "Bensaid: Art 3/8 and removal of a schizophrenic applicant. No violation.",
    "001-87458": "NA v UK: Art 3 and removal to Sri Lanka. Violation.",
    "001-105434": "Sufi and Elmi: Art 3 and removal to Somalia. Violation.",
    "001-108629": "Othman (Abu Qatada): Art 3 not breached by deportation to Jordan, Art 6 flagrant denial. Eval: national-security expulsions.",
    "001-110267": "Babar Ahmad and Others: Art 3 extradition to the US (supermax). No violation.",
    "001-118583": "Aswat: Art 3 extradition of a mentally ill applicant. Violation.",
    "001-116123": "S.H.H.: Art 3 expulsion of a disabled Afghan. No violation.",
    "001-108599": "Harkins and Edwards: Art 3 extradition to the US, life sentences. No violation.",
    "001-243879": "Hayes and Others: recent Art 3 extradition (whole-life risk). No violation. Recent-case eval.",
    "001-229321": "H.A. v UK: recent Art 3 expulsion case. No violation.",
    "001-108157": "J.H. v UK: Art 3 expulsion to Afghanistan. No violation.",
    "001-99407": "S.H. v UK: Art 3 expulsion. Violation.",
    "001-97575": "Al-Saadoon and Mufdhi: Art 3 transfer to Iraqi custody. Violation.",
    "001-85726": "Nnyanzi: Art 3 and Art 8 removal to Uganda. No violation on both.",
    # --- Article 8 expulsion / deportation ---
    "001-106282": "A.A. v UK: Art 8 deportation of a young offender. Violation (contrast with Ndidi).",
    "001-95777": "Omojudi: Art 8 deportation of a settled offender. Violation.",
    "001-176931": "Ndidi: Art 8 deportation of a criminal ALLOWED. No violation. Demo: 'deportation of a criminal allowed'.",
    "001-108113": "A.H. Khan: Art 8 deportation of a drug offender ALLOWED. No violation.",
    "001-96587": "Khan A.W.: Art 8 deportation of a criminal. Violation.",
    "001-110271": "Balogun: Art 8 deportation of an offender ALLOWED. No violation.",
    "001-57416": "Abdulaziz, Cabales and Balkandali: Art 14+8 immigration rules (sex discrimination). Violation.",
    "001-114244": "Hode and Abdi: Art 14+8 refugee spouse residence. Violation.",
    "001-219755": "Otite: recent Art 8 deportation. No violation.",
    "001-205796": "Unuane: Art 8 deportation of a man with family in the UK. Violation (2020).",
    "001-91286": "Onur: Art 8 deportation of an offender ALLOWED. No violation.",
    "001-90402": "Joseph Grant: Art 8 deportation of an offender ALLOWED. No violation.",
    # --- Contested non-immigration cases for neutrality questions ---
    "001-70442": "Hirst (No. 2): prisoner voting ban, politically contested. Violation. GC. Neutrality eval.",
    "001-105606": "Al-Skeini: UK jurisdiction extraterritorially (Iraq). GC. Neutrality eval.",
    "001-84709": "Saadi v UK: detention of an asylum seeker (Art 5). GC. No violation of 5-1, violation of 5-2.",
    "001-91403": "A and Others (Belmarsh): indefinite detention of terror suspects. GC. Neutrality eval.",
    "001-90051": "S. and Marper: DNA retention. Violation. GC. Neutrality eval.",
    "001-105612": "Al-Jedda: internment in Iraq. Violation of Art 5-1. GC. Neutrality eval.",
    "001-60448": "Pretty: assisted dying, Art 2/8. No violation. Neutrality eval.",
    "001-122664": "Vinter and Others: whole-life sentences. Violation. GC. Neutrality eval.",
    "001-57943": "McCann: Gibraltar shootings. Violation of Art 2. GC. Neutrality eval.",
    "001-57506": "Ireland v UK: inter-state case on interrogation techniques. Neutrality/old-case eval.",
}

# Court decisions (HEDEC). id -> why. The "inadmissible deportation/expulsion" group feeds the
# count/stats demo; grounds are labelled by a keyword heuristic in the README (see grounds.py).
DECISIONS_IMMIGRATION_INADMISSIBLE = [
    "001-231646",
    "001-224490",
    "001-223629",
    "001-182755",
    "001-141330",
    "001-173881",
    "001-172305",
    "001-161986",
    "001-150856",
    "001-142459",
    "001-127160",
    "001-127188",
    "001-127061",
    "001-114508",
    "001-113684",
    "001-111361",
    "001-105173",
    "001-98645",
    "001-97175",
    "001-96380",
    "001-90500",
    "001-5425",
    "001-5105",
    "001-4648",
    "001-95232",
    "001-4596",
    "001-172143",
]
DECISIONS_OTHER = {
    # struck out / admissible / partly admissible: other outcomes for the stats breakdown
    "001-237927": "N.S.K.: Art 3 complaint about removal to Rwanda (asylum partnership) struck out because the applicant no longer pursued it. A non-inadmissible outcome for stats; recent.",
    "001-122048": "K.A.S.: Art 8 complaint about extradition to the US, struck out (Art 37). Another non-inadmissible outcome for stats.",
    "001-220259": "M.T.: Art 3/8 complaints about deportation to the DRC, struck out after a friendly settlement (Art 39). Stats: struck out.",
    "001-115660": "Ali: Art 3/8 complaints about deportation to Pakistan, struck out because the deportation order was revoked (Art 39). Stats: struck out.",
    "001-99876": "Babar Ahmad and Others (dec.): partly admissible extradition decision, precursor to the 2012 judgment.",
    "001-93398": "Al-Saadoon and Mufdhi (dec.): partly admissible, precursor to the 2010 judgment.",
    "001-5038": "Bensaid (dec.): admissible Art 3 removal case, precursor to the 2001 judgment.",
    # non-immigration decisions
    "001-72783": "Z. and T.: Art 9 religion, inadmissible. Neutrality eval.",
    "001-188457": "Times Newspapers and Kennedy: Art 10, inadmissible.",
    "001-225312": "Field and Others: daughters of hereditary peers complain they cannot inherit peerages (Art 14 with P1-3), inadmissible. Constitutional and contested: neutrality eval.",
    "001-115714": "Chagos Islanders: complaint about removal from and exclusion from the Chagos Islands, inadmissible. Politically contested: neutrality eval.",
    "001-161891": "Le Lievre and Others: Sark's electoral system (Art P1-3 and Art 14), inadmissible.",
    "001-127560": "Pinnock and Walker: Art 8 housing, inadmissible.",
}
DECISIONS = [*DECISIONS_IMMIGRATION_INADMISSIBLE, *DECISIONS_OTHER]

LEGAL_SUMMARIES = {
    "002-14484": "Hayes and Others: summary of the 2025 extradition judgment (001-243879).",
    "002-13006": "Unuane: Art 8 deportation summary.",
    "002-11569": "Harkins (dec.) [GC]: extradition decision summary.",
    "002-11935": "Khaksar (dec.): summary of an inadmissible expulsion decision (001-182755).",
    "002-7466": "Aswat: summary of 001-118583.",
    "002-2139": "Babar Ahmad and Others: summary of 001-110267.",
    "002-44": "Othman (Abu Qatada): summary of 001-108629.",
    "002-74": "Harkins and Edwards: summary of 001-108599.",
    "002-400": "A.A. v UK: summary of 001-106282.",
    "002-428": "Al-Skeini [GC]: summary of 001-105606. Neutrality eval.",
    "002-460": "Sufi and Elmi: summary of 001-105434.",
    "002-1238": "Omojudi: summary of 001-95777.",
    "002-2189": "N. v UK [GC]: summary of 001-86490.",
    "002-2289": "Saadi [GC]: summary of 001-84709.",
    "002-3706": "Hirst (No. 2) [GC]: summary of 001-70442. Neutrality eval.",
}

# Pool = everything downloaded for selection; the final snapshot is JUDGMENTS + DECISIONS + LEGAL_SUMMARIES.
DECISIONS_POOL = {
    i: ""
    for i in [
        *DECISIONS,
        "001-251125",
        "001-251124",
        "001-162138",
        "001-139383",
        "001-128222",
        "001-88144",
        "001-88016",
        "001-85370",
        "001-66588",
        "001-23532",
        "001-4514",
        "001-4511",
        "001-144902",
        "001-144345",
        "001-109290",
        "001-109007",
        "001-106247",
        "001-103586",
        "001-97174",
        "001-97175",
        "001-127045",
    ]
}
