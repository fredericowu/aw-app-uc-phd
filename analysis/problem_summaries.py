"""Problem summaries for the top-10-per-group projects (sql/top_projects_per_group.sql).

Unlike every other number in this presentation, a 1-3 sentence "what problem
does this solve" summary cannot be computed by SQL — it's a condensation of
free text. Each entry below is manually written, but strictly grounded in
that project's own `synopsis` field (nothing here is invented or generic):
cross-check against `SELECT synopsis FROM projects WHERE id = <key>`, or
against the `synopsis` column top_projects_per_group.sql already returns
alongside these ids, to audit any entry against its source text.

Keyed by `projects.id`. A project's synopsis rarely changes (see repo
README — this DB is a frozen 2026-09-22 snapshot, scraper not re-run), so
this mapping is stable for as long as that snapshot is. If a future
top-10 pulls in a project not covered here, build_presentation.py falls
back to a placeholder rather than inventing a summary silently.
"""

PROBLEM_SUMMARIES = {
    4: (
        "Public spaces in neighbourhoods and urban or rural territories are rarely "
        "designed or managed with community needs and inclusion in mind. UTOPIZE "
        "puts citizens at the centre of reimagining and revitalising these spaces, "
        "starting in Portugal, Italy and Sweden and scaling to six more countries."
    ),
    11: (
        "High-fire-risk areas in Spain, Portugal, France and Andorra lack a "
        "cost-effective way to monitor wildfire risk. SenForFire develops low-cost "
        "wireless sensor networks that measure meteorological and environmental "
        "parameters so municipalities and local communities can prevent and detect "
        "wildfires earlier."
    ),
    16: (
        "Obesity and its metabolic complications are rising across children, "
        "adolescents, young adults and adults, with no personalised way to predict "
        "or intervene on individual risk. PAS-GRAS builds a personalised risk-"
        "assessment algorithm plus tailored lifestyle and dietary interventions, "
        "aiming at a long-term reduction in EU overweight/obesity prevalence."
    ),
    27: (
        "IoT deployments face a growing wave of security incidents — ransomware, "
        "cyber-extortion — that current cybersecurity practices don't adequately "
        "cover, a risk set to worsen with 5G. ARCADIAN-IoT builds a decentralised "
        "trust, security and privacy management framework for IoT, validated in "
        "emergency/drone, grid-monitoring and medical telemonitoring use cases."
    ),
    37: (
        "Verifying and validating automated systems for safety, cybersecurity and "
        "privacy is time-consuming and costly for manufacturers. VALU3S designs a "
        "multi-domain verification-and-validation framework that classifies "
        "methods, tools and environments to cut that overhead."
    ),
    41: (
        "Manufacturers lack a proven way to make circular manufacturing "
        "operational at scale. KYKLOS 4.0 combines cyber-physical systems, PLM, "
        "life-cycle assessment, AR and AI across 7 large-scale pilots to reshape "
        "factory processes, raise operational efficiency and enable material and "
        "component reuse."
    ),
    47: (
        "There is no low-cost, low-power wearable technology for continuous, "
        "accurate lung monitoring outside a clinical setting. WELMO develops "
        "miniaturised sensors integrated into a vest that collect sound and image "
        "signals, processed with new algorithms, to monitor lung condition via "
        "electrical impedance tomography and lung sounds."
    ),
    48: (
        "AI innovation resources are currently dominated by tech giants outside "
        "Europe, leaving European AI capability fragmented and barriers to "
        "innovation high. AI4EU builds a European AI-on-demand platform bundling "
        "algorithms, tools, data and computing resources to lower those barriers; "
        "CISUC's contribution focuses on verifiable, safe and secure AI."
    ),
    56: (
        "Aircraft structure and systems maintenance is not yet real-time or "
        "condition-based, limiting cost and safety benefits and slowing "
        "certification of condition-based maintenance (CBM). ReMAP develops an "
        "Integrated Fleet Health Management solution combining sensing, cloud "
        "analytics and data-driven/physics-based algorithms for real-time "
        "diagnosis, prognosis and adaptive maintenance planning."
    ),
    69: (
        "As IACS/SCADA systems in critical infrastructure (smart grids, water, "
        "oil and gas networks) grow more complex and interconnected, they become "
        "harder to securely configure and monitor, and IT/OT convergence means "
        "they inherit new IT-borne cyber threats. ATENA builds on prior EU "
        "projects (CockpitCI, MICIE) to deliver a modernised security framework "
        "and tools to patch existing IACS without disrupting service."
    ),
    70: (
        "IoT Innovation Hub systems need better ways to pre-process and analyse "
        "large volumes of high-dimensional big data. This project develops "
        "critical feature-selection and sampling techniques to cope with that "
        "dimensionality."
    ),
    76: (
        "Processing the massive data generated by highly connected societies "
        "creates challenges for resource provisioning, performance, quality of "
        "service and privacy in the cloud. EUBra-BIGSEA develops Big Data "
        "capture/federation/annotation services and advanced cloud services "
        "addressing SLAs, QoS and dynamic pricing, demonstrated on high-impact "
        "applications for Europe and Brazil."
    ),
    92: (
        "Management of chronic diseases such as COPD and its comorbidities "
        "(heart failure, diabetes, anxiety/depression) is largely reactive rather "
        "than proactive. WELCOME designs an integrated, patient-centred ecosystem "
        "for early detection of complications and prevention/mitigation of "
        "comorbidities, aiming to reduce hospital admissions."
    ),
    107: (
        "Critical Infrastructures relying on SCADA-based industrial control "
        "networks are vulnerable to cyber threats that undermine their "
        "resilience and dependability. CockpitCI develops risk prediction, "
        "analysis and reaction tools to improve SCADA cybersecurity."
    ),
    124: (
        "Wireless sensor networks deployed in industrial environments lack the "
        "performance guarantees those settings require. GINSENG develops a "
        "performance-controlled WSN targeted at industrial use."
    ),
    129: (
        "Epileptic patients lack a reliable, transportable early-warning system "
        "for seizures. EPILEPSIAE develops a preventive, intelligent alarming "
        "system using semantic mining and multisignal/multidimensional "
        "processing, aiming at improved sensitivity and specificity in detecting "
        "ictal events."
    ),
    143: (
        "Research into large-scale distributed, Grid and peer-to-peer computing "
        "foundations, software infrastructure and applications was fragmented "
        "across Europe. CoreGRID, a European Network of Excellence, coordinated "
        "research to address this gap in Grid computing."
    ),
    144: (
        "Delivering consistent end-to-end quality of service across "
        "heterogeneous networks had unresolved design issues. EuQoS worked to "
        "resolve those issues and enable QoS support across such networks."
    ),
    149: (
        "There was no comprehensive, unified European research area for "
        "technology-enhanced learning. KALEIDOSCOPE builds this research area at "
        "EU/FP6 scale, with CISUC coordinating the Special Interest Group on "
        "Context & Learning."
    ),
    150: (
        "Research into networked audio-visual systems and home platforms was "
        "fragmented across European groups. E-NEXT, an FP6 Network of Excellence "
        "targeted at that call area, coordinated emerging networking experiments "
        "and technologies in this space."
    ),
    151: (
        "Cardio-vascular disease prevention and early diagnosis are hard to "
        "support outside a clinical setting. MyHeart develops a home-based, "
        "mobile system that empowers citizens to fight cardio-vascular disease "
        "through preventive lifestyle changes and early diagnosis."
    ),
    175: (
        "Chronic wounds (pressure, venous, traumatic and diabetic ulcers) are "
        "often complicated by bacterial biofilms and tissue hypoxia that hinder "
        "healing and raise the risk of infection or amputation, while clinical "
        "assessment tools are limited. BioVision develops a portable medical "
        "device combining hyperspectral imaging and AI for real-time bacterial "
        "detection, tissue-oxygenation analysis and clinical decision support."
    ),
    183: (
        "Hospitals lack an efficient logistics system for delivering urgent "
        "pharmaceuticals. PharmaRobot develops autonomous robots for this task, "
        "with CISUC building the AI modules for task allocation, route "
        "optimisation and image-based segmentation/classification."
    ),
    187: (
        "Portugal's sovereign language model AMALIA needed domain-specific "
        "adaptation for science. The University of Coimbra's contribution "
        "focuses on adapting AMALIA to the scientific domain."
    ),
    193: (
        "Businesses and public institutions in the Azores — especially SMEs, and "
        "particularly in tourism, the green economy and manufacturing — lack the "
        "infrastructure, resources and knowledge to digitally transform. AzDIH, "
        "a 13-organisation partnership recognised as an official Digital "
        "Innovation Hub, provides testing, investment support, training and "
        "networking services to drive that transformation."
    ),
    197: (
        "Current machine learning technologies carry risks like bias and lack of "
        "transparency, undermining trust in AI. NextGenAI addresses this by "
        "developing explainable, fairer, more robust and energy-efficient AI "
        "models and human-computer-interaction reliability mechanisms, with "
        "CISUC contributing the underlying algorithms."
    ),
    200: (
        "Portuguese SMEs and public entities lack support for digital and green "
        "transformation, particularly around connectivity and data. CONNECT5, a "
        "12-entity collaborative network spanning cyber-physical systems, IoT, "
        "5G, cloud and big data/AI, helps them test technology solutions, "
        "transfer skills and find funding."
    ),
    203: (
        "The growing number of orbiting satellites raises the risk of space "
        "debris and collisions that can destroy satellites and threaten space "
        "activities. Neuraspace develops an AI-based space traffic management "
        "solution to optimise satellite operators' activities and mitigate that "
        "risk."
    ),
    208: (
        "Logistics and transport networks face challenges and gaps not yet "
        "addressed by an integrated set of digital products and services. NEXUS "
        "builds an ecosystem of 28 products and services — centred on an open "
        "data collaboration platform and digital twins — for the green and "
        "digital transition of transport and logistics."
    ),
    225: (
        "Altice Labs and Portugal's technology sector need to align with "
        "strategic transformation vectors — 5G, edge/cloud computing, "
        "data-driven business models and AI — to build a competitive product and "
        "service portfolio. POWER structures R&D into five subprojects, from "
        "cloud/cognitive infrastructure to future networks, operations, services "
        "and data monetisation, with UC, IT Aveiro and IPN as partners."
    ),
    253: (
        "As 5G standards are set by bodies like 3GPP, Portuguese industry needs "
        "to align and become internationally competitive across the 5G "
        "ecosystem's many segments. This project designs, validates and "
        "integrates a set of 5G products — access, core, control/management, "
        "security and vertical IoT/multimedia — demonstrated in a realistic "
        "campus test environment."
    ),
    321: (
        "Urban transport solutions are often fragmented and not integrated in an "
        "eco-friendly way. TICE.MOBILIDADE explores new, more efficient "
        "urban-transport solutions built on information and communication "
        "technologies to integrate the various available mobility options."
    ),
}
