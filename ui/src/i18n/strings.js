/* ============================================================================
   English and Malayalam strings.

   Translation notes, so the choices here are reviewable rather than opaque:

   1. Technical terms stay in Latin script -- HER2, IHC, DAB, UNET, CPU, PDF,
      JSONL, PNG, α. These are read as-is in Kerala pathology practice and a
      transliteration would make them harder to recognise, not easier.

   2. Clinical vocabulary is transliterated into Malayalam script rather than
      replaced with Sanskritic coinages: പാത്തോളജിസ്റ്റ്, ടിഷ്യു, സ്റ്റെയിൻ,
      സ്കോർ, ബയോപ്സി. This is how Malayalam medical writing and speech
      actually works; "കല" for tissue is dictionary-correct but reads as
      literary Malayalam, not as something a pathologist would say at a
      microscope.

   3. Numerals stay Latin. ml-IN formats this way by default, and Malayalam
      numerals would look archaic on a lab report.

   4. Malayalam has no plural agreement for counted nouns in these
      constructions, so "2 ദിവസം മുൻപ്" is correct with no plural marker --
      the {n}-plus-singular pattern is used throughout rather than the
      English one/other split.

   REVIEW STATUS: the four caveat texts and the safety banner carry clinical
   meaning. They read correctly to me, but they should be signed off by a
   Malayalam-speaking pathologist before this is shown to patients or used in
   a viva -- a mistranslation there is the one that would actually matter.
   ==========================================================================*/

export const STRINGS = {
  /* ------------------------------------------------------------ English --- */
  en: {
    common: {
      appName: "BioMarkHER2",
      tagline: "Pre-scoring review",
      demoData: "Demo data",
      modelOnline: "Model online",
      run: "Run",
      epoch: "Epoch",
      epochShort: "ep. {n}",
      architecture: "Architecture",
      archShort: "Arch",
      language: "Language",
      close: "Close",
      cancel: "Cancel",
      clear: "Clear",
      yes: "Yes",
      no: "No",
      none: "—",
      of: "of",
      loading: "Loading…",
      dash: "—",
      notMedicalDevice:
        "BioMarkHER2 — final-year project, developed with Government Medical College Kottayam. Research and workflow-support use only. Not a medical device and not validated for diagnostic use.",
      researchUseOnly: "Research use only",
      ago: "{n} {unit} ago",
      unit: { second: "second", minute: "minute", hour: "hour", day: "day" },
      unitPlural: { second: "seconds", minute: "minutes", hour: "hours", day: "days" },
      greeting: { morning: "Good morning", afternoon: "Good afternoon", evening: "Good evening" },
    },

    nav: {
      overview: "Overview",
      analysis: "Field analysis",
      cases: "Case log",
      model: "Model card",
      method: "Method & caveats",
      reference: "Reference",
      primary: "Primary",
      portal: "Portal",
      openNav: "Open navigation",
      collapse: "Collapse sidebar",
      expand: "Expand sidebar",
      modelStatusUnknown: "Model status unknown",
    },

    topbar: {
      search: "Search patches, reviewers, case notes",
      searchLabel: "Search",
      notifications: "Notifications",
      activity: "Recent activity",
      activitySub: "Latest sign-offs from the review log",
      activityEmpty: "No sign-offs recorded yet.",
      activityAll: "Open the case log",
      toLight: "Switch to light theme",
      toDark: "Switch to dark theme",
      profile: "Profile",
      preferences: "Preferences",
      signOut: "Sign out",
      registration: "Reg. {id}",
    },

    safety: {
      lead: "This tool does not assign a HER2 score.",
      body:
        "It measures stained tissue area and shows where the staining is. Every figure here needs a pathologist's confirmation.",
    },

    login: {
      title: "Sign in to the portal",
      lede: "Access is limited to registered pathologists at Government Medical College Kottayam.",
      email: "Work email",
      emailPlaceholder: "you@gmck.edu.in",
      password: "Password",
      showPassword: "Show password",
      hidePassword: "Hide password",
      remember: "Keep me signed in",
      needAccess: "Need access?",
      noAccount: "No account yet?",
      createAccount: "Create one",
      submit: "Sign in",
      badCredentials: "Those credentials do not match any account on this browser.",
      demoAccount: "Demo account",
      fill: "Fill",
      disclaimer:
        "These credentials are checked in the browser and authenticate nobody. Research and workflow-support use only — not a medical device, and not validated for diagnostic use.",
      posterChip: "Explainable measurement",
      posterTitle: "See where the stain is, before you score the case.",
      posterBody:
        "Per-pixel intensity mapping over detected tissue, side by side with the classical optical-density baseline it was trained to imitate — so every disagreement between the two is visible rather than hidden inside a single number.",
      statClasses: "Intensity classes mapped",
      statSpeed: "Per 1024² field, laptop CPU",
      statReviewed: "Reviewed by a pathologist",
    },

    profile: {
      eyebrow: "Your account",
      title: "Profile",
      lede:
        "Your name and registration number are written into every assessment you sign, so keep them as they appear on the department register.",
      identity: "Identity",
      identitySub: "Recorded against every field you sign off",
      avatar: "Avatar colour",
      avatarSub: "Identifies you in the case log",
      name: "Full name",
      email: "Work email",
      emailFixed: "The email address identifies the account and cannot be changed here.",
      registration: "Medical registration number",
      role: "Role",
      save: "Save changes",
      saved: "Profile updated",
      savedBody: "Your new details apply to assessments signed from now on.",
      noChanges: "Nothing to save",
      noChangesBody: "Change a field first.",

      prefs: "Preferences",
      prefsSub: "How the portal looks on this machine",
      language: "Language",
      languageSub: "Applies to the whole portal, including every caveat",
      theme: "Theme",
      themeSub: "Stored in this browser only",
      themeLight: "Light",
      themeDark: "Dark",

      security: "Security",
      securitySub: "Change the password for this account",
      current: "Current password",
      next: "New password",
      confirm: "Confirm new password",
      changePassword: "Change password",
      passwordChanged: "Password changed",
      passwordChangedBody: "Use the new password the next time you sign in.",
      wrongCurrent: "That is not your current password.",
      noAccount: "No stored account was found for this address.",
      demoNoPassword:
        "The demo account's password is fixed in the application bundle, so it cannot be changed here.",

      account: "Account",
      accountSub: "What this account is",
      type: "Account type",
      typeDemo: "Built-in demo",
      typeLocal: "Local account",
      created: "Signed in",
      signOut: "Sign out",
      demoNotice:
        "This is the built-in demo account. Edits here last until you sign out — there is no user record to write them to.",
      localNotice:
        "This account exists only in this browser. It grants no privileges and verifies nothing; the details below are what get written into the assessments you sign.",
    },

    landing: {
      nav: {
        method: "Method",
        compare: "Compare",
        limits: "Limits",
        model: "Model card",
        cta: "Open portal",
      },
      hero: {
        line1: "Measured.",
        line2: "Never scored.",
        sub: "BioMarkHER2 maps stained tissue across four HER2 intensity classes and shows exactly where each one sits — then hands the case back to you.",
        cta: "Enter the portal",
      },

      m1: "Per-pixel intensity",
      m2: "DAB optical density",
      m3: "Tissue masking",
      m4: "Conformal confidence",
      m5: "Threshold baseline",
      m6: "Pathologist sign-off",
      m7: "Runs offline",

      info: {
        title: "Meet BioMarkHER2.",
        body: "A measurement aid that reads one IHC field, reports how much tissue falls into each intensity class, and leaves the score where it belongs.",
        cta: "Read the method",
        c1t: "Where the stain sits",
        c1b: "Four DAB intensity classes, assigned per pixel across detected tissue, in one map you can read at a glance.",
        c2t: "Always the baseline,\nalways beside it.",
        c2b: "Every field runs through the classical threshold rule as well. Where the two disagree, you see it happen.",
        c3t: "Never\na score.",
        c3b: "The tool measures and maps. Assigning 0 / 1+ / 2+ / 3+ to a case stays with the pathologist.",
      },

      grounded: {
        lead: "Grounded in published method\nand a working pathology department.",
      },
      r1: "Govt. Medical College Kottayam",
      r2: "ASCO/CAP",
      r3: "CVPR 2022",
      r4: "Additive MIL",
      r5: "Conformal prediction",
      r6: "DAB deconvolution",
      r7: "arXiv:2206.01794",
      r8: "PathAI AIM-HER2",

      use: {
        eyebrow: "BioMarkHER2 in practice",
        title: "Use modes",
        body: "Built for the borderline cases — the fields where thresholds are least reliable and reviewers most often disagree.",
        h3: "Borderline 2+",
        p: "Scroll to wipe the model's intensity map across the original field. In the portal the same control is a handle you drag, so any disagreement between model and baseline is something you look at rather than something averaged away.",
        link: "Open field analysis",
      },

      limits: {
        eyebrow: "What it cannot do",
        title: "The part most tools leave out.",
        body: "This is a research build with real limits. They are on the landing page for the same reason they are on every screen inside: a caveat you have to go looking for is a caveat that gets missed.",
      },
      l1: "It measures area, not cells.",
      l1b: "Percentages are shares of detected tissue. Stroma, lymphocytes and control tissue sit in the denominator. The clinical rule counts invasive tumour cells with complete membrane staining — a different quantity entirely.",
      l2: "It has never seen a pathologist's label.",
      l2b: "It was trained to imitate an optical-density threshold rule, not to reproduce expert scores. Where it disagrees with that rule, it may be right or wrong.",
      l3: "2+ is its weakest class.",
      l3b: "Exactly where the thresholds it learned from are least reliable. Treat a 2+ figure as a prompt to look closely, not a number to quote.",
      l4: "One field is not a case.",
      l4b: "Scoring is a slide-level judgement made on heterogeneity and staining pattern. This sees one field and has no view of the rest of the slide.",

      final: {
        title: "See where the stain is.",
        body: "Open the portal and run a field. Nothing leaves the machine you run it on.",
        cta: "Enter the portal",
      },
      footer:
        "BioMarkHER2 — final-year project, developed with Government Medical College Kottayam. Research and workflow-support use only. Not a medical device and not validated for diagnostic use.",
    },

    signup: {
      title: "Request portal access",
      lede:
        "For pathology staff at Government Medical College Kottayam. Your details are checked against the department register before your first case is assigned.",
      name: "Full name",
      namePlaceholder: "Dr. Anita Menon",
      email: "Work email",
      registration: "Medical registration number",
      registrationPlaceholder: "TC-MC-24817",
      role: "Role",
      password: "Password",
      passwordPlaceholder: "At least 8 characters",
      confirm: "Confirm password",
      terms:
        "I understand this is a research tool, not a medical device, and that every measurement it produces requires my own assessment.",
      submit: "Create account",
      haveAccount: "Already registered?",
      signIn: "Sign in",
      backToSignIn: "Back to sign in",
      strength: "Password strength",
      strengthLevels: ["Too short", "Weak", "Fair", "Good", "Strong"],
      errName: "Enter your full name as it appears on the register.",
      errEmail: "Enter a valid email address.",
      errRegistration: "Enter your medical registration number.",
      errPassword: "Use at least 8 characters, including a letter and a number.",
      errConfirm: "Both passwords must match.",
      errTerms: "Please confirm you understand what this tool is.",
      emailTaken: "An account already exists on this browser for that address.",
      emailIsDemo: "That address belongs to the built-in demo account. Use another.",
      storageBlocked:
        "This browser is blocking site data, so the account could not be saved. Try a normal window.",
      noCrypto:
        "This browser cannot hash the password securely, so the account was not created. Open the portal over HTTPS or localhost.",
      roles: {
        consultant: "Consultant Pathologist",
        seniorResident: "Senior Resident",
        juniorResident: "Junior Resident",
        technician: "Laboratory Technician",
      },
      posterChip: "Departmental access",
      posterTitle: "One reviewer, one signature, on every field.",
      posterBody:
        "Every assessment recorded through this portal carries the name and registration number of the pathologist who made it. The measurements are an input to that judgement — never a substitute for it.",
      noticeLead: "This creates a local account only.",
      noticeBody:
        "There is no user database behind this portal yet, so the account lives in this browser and nowhere else. It grants no privileges and verifies nothing. Your password is salted and hashed before it is stored, so it is never held in plain text — but treat this as a demo, and do not reuse a password that matters.",
    },

    dash: {
      lede:
        "{n} fields reviewed on this workstation. Concordance between the measurements and your reading is running at {pct}.",
      ledeOne:
        "{n} field reviewed on this workstation. Concordance between the measurements and your reading is running at {pct}.",
      ledeNone:
        "Nothing reviewed on this workstation yet. Analyse a field and record your assessment to start the log.",
      kpiReviewed: "Fields reviewed",
      kpiReviewedFoot: "in the last 7 days",
      kpiDelta: "vs. prior 7 days · {n} this week",
      throughputTotal: "{n} in 14 days",
      throughputEmpty: "No sign-offs in the last 14 days.",
      yours: "Yours",
      team: "All reviewers",
      thisWeek: "This week",
      recentSubDemo: "Demo history — the backend is not running",
      kpiConcordant: "Measurements concordant",
      kpiConcordantFoot: "{a} of {b} sign-offs agreed with the maps",
      kpiFlagged: "Flagged for disagreement",
      kpiFlaggedFoot: "Reviewer marked the maps inconsistent with the field",
      kpiUnassessable: "Not assessable",
      kpiUnassessableFoot: "Insufficient invasive tumour in the field",
      benchOn: "Field on the bench",
      benchOff: "Nothing on the bench",
      benchSubOn: "{id} · {w}×{h}",
      benchSubOff: "Load a field to see its intensity map and area measurements here.",
      benchEmpty:
        "Pick an example patch from the training dataset, or drop in an IHC field of your own. Nothing is uploaded anywhere.",
      chooseField: "Choose a field",
      open: "Open",
      start: "Start",
      largestClass: "Largest stained-area class",
      measurementNotScore: "{pct} of detected tissue — a measurement, not a score",
      throughput: "Review throughput",
      throughputSub: "Fields signed off per day, last 14 days",
      recent: "Recent sign-offs",
      recentSub: "From the server's review log, newest first",
      viewAll: "View all",
      noneRecorded: "No assessments recorded yet.",
      signOffs: "Sign-offs",
      flagged: "Flagged",
      mix: "Assessment mix",
      mixSub: "Scores assigned by reviewers",
      concordance: "Concordance",
      concordanceSub: "Reviewer agreed with the maps",
      concordanceNote:
        "Concordance here means the reviewer ticked “the measurements are consistent with what I see”. It is not an accuracy figure: the model was never trained against pathologist labels.",
      deployment: "Deployment",
      deploymentSub: "What is answering right now",
      source: "Source",
      sourceDemo: "Demo data (backend unreachable)",
      sourceLive: "Live backend",
      analyseField: "Analyse a field",
      caseLog: "Case log",
    },

    table: {
      field: "Field",
      assessment: "Assessment",
      datasetLabel: "Dataset label",
      tissue: "Tissue",
      reviewer: "Reviewer",
      concordant: "Concordant",
      notes: "Notes",
      recorded: "Recorded",
      when: "When",
      flagged: "Flagged",
      intensityClass: "Intensity class",
      model: "Model",
      baseline: "Threshold baseline",
      difference: "Difference",
      share: "Share",
    },

    analysis: {
      steps: "Step 1 · Choose a field  ·  Step 2 · Review",
      title: "Field analysis",
      lede:
        "Run one IHC field through the model and the threshold baseline together, then record your own assessment against what you can see.",
      pdfReport: "PDF report",
      analyse: "Analyse field",
      source: "Field source",
      upload: "Upload",
      samplePatch: "Example patch from the training dataset",
      noSamples: "No sample patches found",
      sampleHint:
        "Dataset patch label: {label}. Shown for comparison — it is the dataset's own label, not a pathologist's reading of this field.",
      or: "or",
      dropTitle: "Drop an IHC field, or browse",
      dropSub: "PNG, JPEG or TIFF · kept on this machine, nothing is uploaded",
      clearUpload: "Clear upload",
      keyResult: "Key result",
      measurement: "Measurement",
      largestClass: "Largest stained-area class",
      sourceLabel: "This field's dataset label is {label}",
      pickClassLabel: "No dataset label for this field — pick a class to inspect",
      classPickerLabel: "Intensity class to inspect",
      ofTissue: "{pct} of detected tissue",
      seeWhere: "See where this class is",
      notAScoreLead: "This is",
      notAScoreBold: "not",
      notAScoreRest:
        " a HER2 score. It is how much of this field's tissue area falls into the selected intensity class. Scoring the case remains yours.",
      heatLegend: "DAB optical density",
      heatLow: "unstained",
      tissueCoverage: "Tissue coverage",
      tissueCoverageNote:
        "Tissue fills {pct} of this {w}×{h} field. Every percentage above is a share of that area — not a share of tumour cells.",
      supporting: "Supporting results",
      disagreement: "Model / baseline disagreement",
      disagreementHint: "of tissue pixels assigned a different class by each method",
      ambiguous: "Ambiguous at α={alpha}",
      ambiguousHint: "calibrated prediction set holds more than one class",
      staleCalibration:
        "This calibration was computed against a different checkpoint than the one loaded — the ambiguity figures may not reflect the running model. Re-run",
      signoff: "Pathologist sign-off",
      yourAssessment: "HER2 score for this field — your assessment",
      cannotAssess: "Cannot assess",
      agrees: "The measurements above are consistent with what I see",
      notesLabel: "Notes (optional)",
      notesPlaceholder:
        "Membrane completeness, staining pattern, artefacts — anything the intensity map misses",
      signingAs: "Signing as",
      record: "Record my assessment",
      compare: "Compare",
      compareTitle: "Wipe between the model map and the threshold baseline",
      enlarge: "Enlarge",
      layers: "Image layers",
      emptyTitle: "No field loaded",
      emptyBody:
        "Pick an example patch or drop in an IHC image on the left, then run the analysis. Nothing leaves this machine.",
      tableTitle: "Stained area, as a percentage of detected tissue",
      tableSub:
        "Not a percentage of tumour cells. Stroma, lymphocytes, normal ducts and control tissue are all inside this denominator.",
      leastReliable: "least reliable",
      summary: "Model and baseline disagree on {pct} of tissue pixels.",
      summaryConformal:
        " At significance level α={alpha}, {pct} of tissue pixels have an ambiguous prediction set.",
      caveatsTitle: "What these numbers are, and are not",
      caveatsSub: "Reprinted verbatim in the PDF report",
      fullMethod: "Full method",
      compareCaption: "Model intensity map vs. threshold baseline",
      compareNote:
        "Drag the handle. Left of it is the model; right of it is the classical threshold rule. Where the two differ, the model is generalising beyond its pseudo-labels — which may be right or wrong.",
      modelNote: "{arch}, trained on threshold pseudo-labels. Background left unpainted.",
      theModel: "The model",
      views: {
        original: "Original",
        originalNote: "As scanned, before any processing.",
        tissue: "Tissue mask",
        tissueNote:
          "Everything outside this mask is excluded from the percentages in the rail.",
        model: "Intensity map",
        isolate: "Where: {label}",
        isolateNote:
          "Only the selected intensity class is painted; every other class and all background is shown as scanned — so a class that is a small share of a busy field is still easy to find.",
        heatmap: "DAB heatmap",
        heatmapNote:
          "The same DAB signal as the intensity map, without being bucketed into the four classes — a borderline pixel reads as a colour between two classes instead of being forced into one of them.",
        baseline: "Threshold baseline",
        baselineNote:
          "Classical DAB optical-density thresholds — the rule the model was trained to imitate.",
        ambiguity: "Confidence",
        ambiguityNote:
          "Where the model's calibrated prediction set narrows to a single class (confident) versus more than one (ambiguous). A confidence map, not a class map.",
      },
      tabs: {
        original: "Original",
        tissue: "Tissue",
        model: "Intensity",
        isolate: "Where {label}",
        heatmap: "Heatmap",
        baseline: "Baseline",
        ambiguity: "Confidence",
      },
      annotate: {
        title: "Field annotations",
        listSub: "Regions marked on the image above, in the order they were saved",
        hint: "Drag on the image to mark a region",
        toggle: "Annotate",
        done: "Done",
        toggleTitle: "Mark regions on the field — Esc to stop",
        notePlaceholder: "What did you notice here?",
        cancel: "Cancel",
        save: "Save annotation",
        savedTitle: "Annotation saved",
        savedLive: "Written to the server-side log.",
        savedDemo: "Kept for this session only — the backend is not running.",
        failedTitle: "Could not save the annotation",
      },
    },

    cases: {
      eyebrow: "Sign-off history",
      title: "Case log",
      demoRows: "Demo history",
      lede:
        "Every assessment recorded from this workstation. The server-side JSONL log written by {path} remains the record of truth; this is a convenience view of it.",
      all: "All",
      flagged: "Flagged",
      concordant: "Concordant",
      unassessable: "Not assessable",
      filterLabel: "Filter assessments",
      search: "Search patch, reviewer or note",
      searchLabel: "Search assessments",
      emptyTitle: "Nothing matches that",
      emptyBody: "Clear the search, or pick a different filter.",
      footnote:
        "“Concordant” records only whether the reviewer ticked <i>the measurements are consistent with what I see</i>. It is not a measure of the model's accuracy: the model was trained on optical-density pseudo-labels and has never seen a pathologist's label.",
    },

    model: {
      eyebrow: "Documentation",
      title: "Model card",
      lede: "What the deployed checkpoint is, what it was trained on, and the four things it cannot do.",
      spec: "Specification",
      specSub: "This deployment",
      limitations: "Known limitations",
      limitationsSub: "Read these before quoting any figure from this tool",
      comparison: "For comparison — a cleared commercial system",
      comparisonSub:
        "PathAI AIM-HER2 Breast Cancer. Somebody else's product, listed here to show what a validated system in this space looks like. None of its performance carries over to this project.",
      comparisonNote:
        "The important difference: AIM-HER2 predicts a slide-level score and was trained against board-certified pathologist reads. This project predicts per-pixel stain intensity from threshold pseudo-labels and deliberately declines to produce a score.",
      checkpoint: "Deployed checkpoint",
      checkpointSub: "Reported by the server at load",
      checkpointLabel: "Checkpoint",
      trained: "Trained",
      demoWarning:
        "The backend is not reachable, so these values are placeholders from the demo module — not a running checkpoint.",
      classes: "Intensity classes",
      classesSub: "Palette supplied by the server",
      classIndex: "index {i} · {color}",
      classesNote:
        "The legend, the intensity map and the results table all read this palette, so they can never drift apart. The DAB heatmap uses its own heat scale, anchored at the same three thresholds:",
      specs: {
        intendedUse: "Intended use",
        intendedUseBody:
          "Research and workflow support only. Not a medical device; not validated for diagnostic use.",
        task: "Task",
        taskBody:
          "Per-pixel stain-intensity segmentation over detected tissue. The model does not output a case-level HER2 score.",
        indication: "Indication",
        indicationBody: "Breast cancer HER2 immunohistochemistry",
        inputs: "Inputs",
        inputsBody: "A single IHC field as PNG, JPEG or TIFF. Whole-slide images are not supported.",
        outputs: "Outputs",
        outputsBody:
          "Tissue mask; four-class intensity map; per-class stained area as a percentage of detected tissue; conformal prediction-set ambiguity map where a calibration is loaded.",
        targets: "Training targets",
        targetsBody:
          "Pseudo-labels derived from classical DAB optical-density thresholds. No pathologist annotations were used.",
        site: "Development site",
        siteBody: "Government Medical College Kottayam",
      },
      ref: {
        intendedUse: "Intended use",
        intendedUseBody: "Research Use Only",
        outputs: "Outputs",
        outputsBody:
          "HER2 score (0, 1+, 2+, 3+); area of invasive carcinoma; additive multiple-instance learning (aMIL) density heatmap",
        clones: "Clones",
        clonesBody: "Ventana 4B5 and Dako HercepTest",
        scanners: "Scanners",
        scannersBody: "Leica Aperio AT2 and GT450; Hamamatsu NanoZoomer s360",
        inputs: "Inputs",
        inputsBody:
          "Whole-slide biopsy, resection or excision from primary, recurrent or metastatic tumour, excluding in-situ tumour",
        reference: "Reference",
      },
      limits: {
        areaTitle: "It measures area, not cells",
        areaBody:
          "Percentages are shares of detected tissue area. Stroma, lymphocytes, normal ducts and control tissue all sit inside the denominator. The clinical rule counts invasive tumour cells with complete membrane staining — a different quantity, computed over a different population.",
        twoTitle: "The 2+ class is the weak one",
        twoBody:
          "2+ is exactly where optical-density thresholds are least reliable, and thresholds are all this model ever learned from. Treat a 2+ area figure as a prompt to look closely, not as a number to quote.",
        labelTitle: "It has never seen a pathologist's label",
        labelBody:
          "The model was trained to imitate a threshold rule. Where it disagrees with the baseline, that is generalisation — which may be an improvement or an error. Both columns are shown side by side so the disagreement is visible rather than averaged away.",
        fieldTitle: "One field is not a case",
        fieldBody:
          "Scoring is a slide-level and case-level judgement made on heterogeneity, membrane completeness and staining pattern. This tool sees one field at a time and has no view of the rest of the slide.",
      },
    },

    method: {
      eyebrow: "Documentation",
      title: "Method & caveats",
      lede: "What the numbers on the analysis screen are, and — more importantly — what they are not.",
      caveatsTitle: "What these numbers are, and are not",
      caveatsSub: "Served alongside every analysis, and reprinted in every PDF report",
      pipeline: "How a field is processed",
      pipelineSub: "Five steps, none of which produce a score",
      step: "Step {n}",
      notDeviceLead: "Not a medical device.",
      notDeviceBody:
        "BioMarkHER2 is a final-year project developed with Government Medical College Kottayam, for research and workflow-support use. It has not been validated for diagnostic use and must not be used to make a clinical decision on its own.",
      dataTitle: "Data handling",
      dataSub: "Where images go",
      refTitle: "Reference",
      refSub: "Background reading",
      caveatTitles: {
        not_a_score: "What this tool is",
        denominator: "Whose percentage this is",
        targets: "What the model learned from",
        model_limitation: "The 2+ class",
      },
      steps: {
        detectTitle: "Detect tissue",
        detectBody:
          "A tissue mask separates section from slide background. Everything outside it is excluded from every percentage the tool reports.",
        classifyTitle: "Classify stain intensity",
        classifyBody:
          "Each tissue pixel is assigned one of four DAB intensity classes. This is a per-pixel segmentation, not a cell-level or membrane-level analysis.",
        baselineTitle: "Run the threshold baseline",
        baselineBody:
          "The same field is passed through the classical optical-density threshold rule the model was trained to imitate, and both results are reported side by side.",
        quantifyTitle: "Quantify the disagreement",
        quantifyBody:
          "The share of tissue pixels the two methods classify differently is reported as a single figure, and — where a conformal calibration is loaded — so is the share whose calibrated prediction set holds more than one class.",
        handTitle: "Hand it to a pathologist",
        handBody:
          "Nothing is recorded until a named reviewer selects a score and submits. The tool's own output is never treated as an assessment.",
      },
      data: {
        localTitle: "Uploads stay local",
        localBody:
          "An uploaded field is read in the browser and posted to the local backend. Nothing is sent to a third party.",
        logTitle: "Reviews are logged locally",
        logBody:
          "Submitted assessments are appended to a JSONL file on the machine running the server.",
        reportTitle: "Reports are rendered server-side",
        reportBody:
          "The PDF contains the same images, measurements and caveats shown on screen — no more, and no fewer.",
      },
      refs: {
        amilTitle:
          "Additive MIL: Intrinsically Interpretable Multiple Instance Learning from Pathology",
        amilMeta: "Javed et al., CVPR 2022 · arXiv:2206.01794",
        pathaiTitle: "PathAI AIM-HER2 Breast Cancer",
        pathaiMeta: "A commercial system in the same space, for comparison",
      },
    },

    toast: {
      dismiss: "Dismiss notification",
      demoTitle: "Showing demo data",
      demoBody: "The Python backend is not reachable from this page.",
      analysedTitle: "Field analysed",
      analysedBody: "Review the measurements before recording an assessment.",
      analysisFailed: "Analysis failed",
      selectTitle: "Select an assessment",
      selectBody: "Choose a score, or “Cannot assess”.",
      recordedTitle: "Assessment recorded",
      recordedDemo: "Held in this browser only — no backend to write to.",
      recordedLive: "Written to {log}",
      recordFailed: "Could not record that",
      reportTitle: "Report downloaded",
      reportBody: "Images, measurements and every caveat as shown.",
      reportFailed: "Report unavailable",
      chooseFirst: "Choose an example patch or upload an image first.",
    },

    /* Seeded demo content. A note the pathologist actually typed is never
       translated -- only these placeholder ones are. */
    demo: {
      role: "Consultant Pathologist",
      department: "Pathology · Govt. Medical College Kottayam",
      notes: {
        heterogeneous: "Heterogeneous; reflex to ISH requested.",
        strong: "Strong complete membrane staining throughout.",
        crush: "Model over-calls 1+ on crush artefact at the upper edge.",
        insufficient: "Insufficient invasive tumour in this field.",
      },
    },

    caveats: {
      not_a_score:
        "This tool does not assign a HER2 score. It measures how much of the detected tissue falls into each stain-intensity class and shows you where. Assigning 0 / 1+ / 2+ / 3+ to a case remains a pathologist's judgement, made on membrane completeness and staining pattern across the whole slide — not on an area percentage from one field.",
      model_limitation:
        "The 2+ class is the weakest part of this model. It was trained on pseudo-labels derived from optical-density thresholds, and 2+ is exactly where those thresholds are least reliable. Treat any 2+ area figure as a prompt to look, not as a measurement to quote.",
      targets:
        "The model was trained to imitate a classical DAB optical-density threshold rule, not to reproduce pathologist scores. It has never seen a pathologist's label. Where it disagrees with the threshold baseline, that is the model generalising — which may be right or wrong, and the two columns are shown side by side so you can see it happen.",
      denominator:
        "Every percentage below is a share of detected tissue area, not a share of tumour cells. Stroma, lymphocytes, normal ducts and control tissue are all inside the denominator. The clinical rule counts invasive tumour cells with complete membrane staining, which is a different quantity entirely.",
    },
  },

  /* ---------------------------------------------------------- Malayalam --- */
  ml: {
    common: {
      appName: "BioMarkHER2",
      tagline: "സ്കോറിങ്ങിനു മുൻപുള്ള പരിശോധന",
      demoData: "ഡെമോ ഡാറ്റ",
      modelOnline: "മോഡൽ ഓൺലൈൻ",
      run: "റൺ",
      epoch: "എപ്പോക്ക്",
      epochShort: "എപ്പോക്ക് {n}",
      architecture: "ആർക്കിടെക്ചർ",
      archShort: "ആർക്ക്",
      language: "ഭാഷ",
      close: "അടയ്ക്കുക",
      cancel: "റദ്ദാക്കുക",
      clear: "മായ്ക്കുക",
      yes: "അതെ",
      no: "അല്ല",
      none: "—",
      of: "/",
      loading: "വരുന്നു…",
      dash: "—",
      notMedicalDevice:
        "BioMarkHER2 — കോട്ടയം ഗവൺമെന്റ് മെഡിക്കൽ കോളേജുമായി ചേർന്ന് വികസിപ്പിച്ച അവസാനവർഷ പ്രോജക്ട്. ഗവേഷണത്തിനും ജോലിക്രമത്തിനുള്ള പിന്തുണയ്ക്കും മാത്രം. ഇതൊരു മെഡിക്കൽ ഉപകരണമല്ല; രോഗനിർണയത്തിനായി സാധൂകരിച്ചിട്ടുമില്ല.",
      researchUseOnly: "ഗവേഷണ ഉപയോഗത്തിനു മാത്രം",
      ago: "{n} {unit} മുൻപ്",
      unit: { second: "സെക്കൻഡ്", minute: "മിനിറ്റ്", hour: "മണിക്കൂർ", day: "ദിവസം" },
      unitPlural: { second: "സെക്കൻഡ്", minute: "മിനിറ്റ്", hour: "മണിക്കൂർ", day: "ദിവസം" },
      greeting: { morning: "സുപ്രഭാതം", afternoon: "നമസ്കാരം", evening: "ശുഭസന്ധ്യ" },
    },

    nav: {
      overview: "അവലോകനം",
      analysis: "ഫീൽഡ് വിശകലനം",
      cases: "കേസ് രേഖ",
      model: "മോഡൽ കാർഡ്",
      method: "രീതിയും മുന്നറിയിപ്പുകളും",
      reference: "അവലംബം",
      primary: "പ്രധാന മെനു",
      portal: "പോർട്ടൽ",
      openNav: "മെനു തുറക്കുക",
      collapse: "സൈഡ്‌ബാർ ചുരുക്കുക",
      expand: "സൈഡ്‌ബാർ വികസിപ്പിക്കുക",
      modelStatusUnknown: "മോഡലിന്റെ നില അറിയില്ല",
    },

    topbar: {
      search: "പാച്ചുകൾ, പരിശോധകർ, കേസ് കുറിപ്പുകൾ തിരയുക",
      searchLabel: "തിരയുക",
      notifications: "അറിയിപ്പുകൾ",
      toLight: "ലൈറ്റ് തീമിലേക്ക് മാറുക",
      toDark: "ഡാർക്ക് തീമിലേക്ക് മാറുക",
      profile: "പ്രൊഫൈൽ",
      preferences: "ക്രമീകരണങ്ങൾ",
      signOut: "സൈൻ ഔട്ട്",
      registration: "രജി. {id}",
      activity: "സമീപകാല പ്രവർത്തനം",
      activitySub: "റിവ്യൂ ലോഗിലെ ഏറ്റവും പുതിയ ഒപ്പുവയ്ക്കലുകൾ",
      activityEmpty: "ഇതുവരെ ഒപ്പുവയ്ക്കലുകളൊന്നും രേഖപ്പെടുത്തിയിട്ടില്ല.",
      activityAll: "കേസ് ലോഗ് തുറക്കുക",
    },

    safety: {
      lead: "ഈ ഉപകരണം HER2 സ്കോർ നിർണയിക്കുന്നില്ല.",
      body:
        "ഇത് സ്റ്റെയിൻ ചെയ്ത ടിഷ്യുവിന്റെ വിസ്തീർണം അളക്കുകയും സ്റ്റെയിനിങ് എവിടെയാണെന്ന് കാണിക്കുകയും മാത്രമാണ് ചെയ്യുന്നത്. ഇവിടെയുള്ള ഓരോ കണക്കിനും ഒരു പാത്തോളജിസ്റ്റിന്റെ സ്ഥിരീകരണം ആവശ്യമാണ്.",
    },

    login: {
      title: "പോർട്ടലിലേക്ക് സൈൻ ഇൻ ചെയ്യുക",
      lede:
        "കോട്ടയം ഗവൺമെന്റ് മെഡിക്കൽ കോളേജിൽ രജിസ്റ്റർ ചെയ്ത പാത്തോളജിസ്റ്റുകൾക്കു മാത്രമാണ് പ്രവേശനം.",
      email: "ഔദ്യോഗിക ഇമെയിൽ",
      emailPlaceholder: "you@gmck.edu.in",
      password: "പാസ്‌വേഡ്",
      showPassword: "പാസ്‌വേഡ് കാണിക്കുക",
      hidePassword: "പാസ്‌വേഡ് മറയ്ക്കുക",
      remember: "സൈൻ ഇൻ ചെയ്തതായി തുടരുക",
      needAccess: "പ്രവേശനം വേണോ?",
      noAccount: "അക്കൗണ്ട് ഇല്ലേ?",
      createAccount: "ഒന്ന് ഉണ്ടാക്കുക",
      submit: "സൈൻ ഇൻ",
      badCredentials: "ഈ ബ്രൗസറിലെ ഒരു അക്കൗണ്ടുമായും ഈ വിവരങ്ങൾ പൊരുത്തപ്പെടുന്നില്ല.",
      demoAccount: "ഡെമോ അക്കൗണ്ട്",
      fill: "പൂരിപ്പിക്കുക",
      disclaimer:
        "ഈ വിവരങ്ങൾ ബ്രൗസറിൽ മാത്രമാണ് പരിശോധിക്കുന്നത്; ഇവ ആരെയും ആധികാരികമായി തിരിച്ചറിയുന്നില്ല. ഗവേഷണത്തിനും ജോലിക്രമത്തിനുള്ള പിന്തുണയ്ക്കും മാത്രം — ഇതൊരു മെഡിക്കൽ ഉപകരണമല്ല, രോഗനിർണയത്തിനായി സാധൂകരിച്ചിട്ടുമില്ല.",
      posterChip: "വിശദീകരിക്കാവുന്ന അളവെടുപ്പ്",
      posterTitle: "കേസ് സ്കോർ ചെയ്യും മുൻപ്, സ്റ്റെയിൻ എവിടെയാണെന്ന് കാണുക.",
      posterBody:
        "കണ്ടെത്തിയ ടിഷ്യുവിന് മേൽ പിക്സൽ തലത്തിലുള്ള തീവ്രതാ മാപ്പിങ്, അതിനൊപ്പം മോഡൽ അനുകരിക്കാൻ പഠിച്ച പരമ്പരാഗത ഒപ്റ്റിക്കൽ-ഡെൻസിറ്റി ബേസ്‌ലൈനും — അങ്ങനെ ഇവ രണ്ടും തമ്മിലുള്ള ഓരോ വ്യത്യാസവും ഒറ്റ സംഖ്യയ്ക്കുള്ളിൽ മറയാതെ കാണാം.",
      statClasses: "മാപ്പ് ചെയ്ത തീവ്രതാ വിഭാഗങ്ങൾ",
      statSpeed: "ഓരോ 1024² ഫീൽഡിനും, ലാപ്‌ടോപ്പ് CPU-യിൽ",
      statReviewed: "പാത്തോളജിസ്റ്റ് പരിശോധിക്കുന്നു",
    },

    profile: {
      eyebrow: "താങ്കളുടെ അക്കൗണ്ട്",
      title: "പ്രൊഫൈൽ",
      lede:
        "താങ്കൾ ഒപ്പിടുന്ന ഓരോ വിലയിരുത്തലിലും പേരും രജിസ്ട്രേഷൻ നമ്പറും രേഖപ്പെടുത്തുന്നു; അതിനാൽ വകുപ്പിന്റെ രജിസ്റ്ററിൽ ഉള്ളതുപോലെ തന്നെ അവ സൂക്ഷിക്കുക.",
      identity: "വ്യക്തിവിവരങ്ങൾ",
      identitySub: "താങ്കൾ ഒപ്പിടുന്ന ഓരോ ഫീൽഡിലും രേഖപ്പെടുത്തുന്നു",
      avatar: "അവതാർ നിറം",
      avatarSub: "കേസ് രേഖയിൽ താങ്കളെ തിരിച്ചറിയാൻ",
      name: "പൂർണനാമം",
      email: "ഔദ്യോഗിക ഇമെയിൽ",
      emailFixed: "ഇമെയിൽ വിലാസമാണ് അക്കൗണ്ടിനെ തിരിച്ചറിയുന്നത്; അത് ഇവിടെ മാറ്റാനാകില്ല.",
      registration: "മെഡിക്കൽ രജിസ്ട്രേഷൻ നമ്പർ",
      role: "പദവി",
      save: "മാറ്റങ്ങൾ സൂക്ഷിക്കുക",
      saved: "പ്രൊഫൈൽ പുതുക്കി",
      savedBody: "ഇനി മുതൽ ഒപ്പിടുന്ന വിലയിരുത്തലുകൾക്ക് പുതിയ വിവരങ്ങൾ ബാധകമാണ്.",
      noChanges: "സൂക്ഷിക്കാൻ ഒന്നുമില്ല",
      noChangesBody: "ആദ്യം എന്തെങ്കിലും മാറ്റുക.",

      prefs: "ക്രമീകരണങ്ങൾ",
      prefsSub: "ഈ കമ്പ്യൂട്ടറിൽ പോർട്ടൽ എങ്ങനെ കാണപ്പെടുന്നു",
      language: "ഭാഷ",
      languageSub: "എല്ലാ മുന്നറിയിപ്പുകളുമടക്കം മുഴുവൻ പോർട്ടലിനും ബാധകം",
      theme: "തീം",
      themeSub: "ഈ ബ്രൗസറിൽ മാത്രം സൂക്ഷിക്കുന്നു",
      themeLight: "ലൈറ്റ്",
      themeDark: "ഡാർക്ക്",

      security: "സുരക്ഷ",
      securitySub: "ഈ അക്കൗണ്ടിന്റെ പാസ്‌വേഡ് മാറ്റുക",
      current: "നിലവിലെ പാസ്‌വേഡ്",
      next: "പുതിയ പാസ്‌വേഡ്",
      confirm: "പുതിയ പാസ്‌വേഡ് ഉറപ്പിക്കുക",
      changePassword: "പാസ്‌വേഡ് മാറ്റുക",
      passwordChanged: "പാസ്‌വേഡ് മാറ്റി",
      passwordChangedBody: "അടുത്ത തവണ സൈൻ ഇൻ ചെയ്യുമ്പോൾ പുതിയ പാസ്‌വേഡ് ഉപയോഗിക്കുക.",
      wrongCurrent: "ഇത് താങ്കളുടെ നിലവിലെ പാസ്‌വേഡ് അല്ല.",
      noAccount: "ഈ വിലാസത്തിൽ സൂക്ഷിച്ച അക്കൗണ്ട് കണ്ടെത്തിയില്ല.",
      demoNoPassword:
        "ഡെമോ അക്കൗണ്ടിന്റെ പാസ്‌വേഡ് ആപ്ലിക്കേഷൻ ബണ്ടിലിൽ നിശ്ചയിച്ചിട്ടുള്ളതാണ്; അത് ഇവിടെ മാറ്റാനാകില്ല.",

      account: "അക്കൗണ്ട്",
      accountSub: "ഈ അക്കൗണ്ട് എന്താണ്",
      type: "അക്കൗണ്ട് തരം",
      typeDemo: "ഉൾച്ചേർത്ത ഡെമോ",
      typeLocal: "ലോക്കൽ അക്കൗണ്ട്",
      created: "സൈൻ ഇൻ ചെയ്തത്",
      signOut: "സൈൻ ഔട്ട്",
      demoNotice:
        "ഇത് ഉൾച്ചേർത്ത ഡെമോ അക്കൗണ്ടാണ്. ഇവിടെ വരുത്തുന്ന മാറ്റങ്ങൾ സൈൻ ഔട്ട് ചെയ്യുന്നതുവരെ മാത്രം നിലനിൽക്കും — അവ എഴുതിവയ്ക്കാൻ ഒരു യൂസർ രേഖയില്ല.",
      localNotice:
        "ഈ അക്കൗണ്ട് ഈ ബ്രൗസറിൽ മാത്രമേ ഉള്ളൂ. ഇത് ഒരു അധികാരവും നൽകുന്നില്ല, ഒന്നും പരിശോധിച്ച് ഉറപ്പാക്കുന്നുമില്ല; താഴെയുള്ള വിവരങ്ങളാണ് താങ്കൾ ഒപ്പിടുന്ന വിലയിരുത്തലുകളിൽ രേഖപ്പെടുത്തുന്നത്.",
    },

    landing: {
      nav: {
        method: "രീതി",
        compare: "താരതമ്യം",
        limits: "പരിമിതികൾ",
        model: "മോഡൽ കാർഡ്",
        cta: "പോർട്ടൽ തുറക്കുക",
      },
      hero: {
        line1: "അളക്കുന്നു.",
        line2: "സ്കോർ നൽകുന്നില്ല.",
        sub: "നാല് HER2 തീവ്രതാ വിഭാഗങ്ങളിലായി സ്റ്റെയിൻ ചെയ്ത ടിഷ്യു മാപ്പ് ചെയ്ത്, ഓരോന്നും എവിടെയാണെന്ന് കാണിച്ചശേഷം BioMarkHER2 കേസ് താങ്കൾക്കുതന്നെ തിരികെ നൽകുന്നു.",
        cta: "പോർട്ടലിലേക്ക് പ്രവേശിക്കുക",
      },

      m1: "പിക്സൽ തല തീവ്രത",
      m2: "DAB ഒപ്റ്റിക്കൽ ഡെൻസിറ്റി",
      m3: "ടിഷ്യു മാസ്ക്",
      m4: "കൺഫോർമൽ വിശ്വാസ്യത",
      m5: "ത്രെഷോൾഡ് ബേസ്‌ലൈൻ",
      m6: "പാത്തോളജിസ്റ്റിന്റെ ഒപ്പ്",
      m7: "ഓഫ്‌ലൈനിൽ പ്രവർത്തിക്കുന്നു",

      info: {
        title: "BioMarkHER2 പരിചയം.",
        body: "ഒരു IHC ഫീൽഡ് വായിച്ച്, ഓരോ തീവ്രതാ വിഭാഗത്തിലും എത്ര ടിഷ്യു വരുന്നു എന്ന് അറിയിക്കുന്ന ഒരു അളവെടുപ്പ് ഉപകരണം; സ്കോർ അതിന്റെ സ്ഥാനത്ത് തന്നെ നിൽക്കുന്നു.",
        cta: "രീതി വായിക്കുക",
        c1t: "സ്റ്റെയിൻ എവിടെയാണ്",
        c1b: "കണ്ടെത്തിയ ടിഷ്യുവിന് മേൽ ഓരോ പിക്സലിനും നാല് DAB തീവ്രതാ വിഭാഗങ്ങളിൽ ഒന്ന് — ഒറ്റനോട്ടത്തിൽ വായിക്കാവുന്ന ഒരു മാപ്പിൽ.",
        c2t: "എപ്പോഴും ബേസ്‌ലൈൻ,\nഎപ്പോഴും അടുത്തുതന്നെ.",
        c2b: "ഓരോ ഫീൽഡും പരമ്പരാഗത ത്രെഷോൾഡ് നിയമത്തിലൂടെയും കടത്തിവിടുന്നു. അവ വിയോജിക്കുന്നിടത്ത് താങ്കൾ അത് കാണുന്നു.",
        c3t: "ഒരിക്കലും\nഒരു സ്കോർ അല്ല.",
        c3b: "ഉപകരണം അളക്കുകയും മാപ്പ് ചെയ്യുകയും ചെയ്യുന്നു. ഒരു കേസിന് 0 / 1+ / 2+ / 3+ നൽകുന്നത് പാത്തോളജിസ്റ്റിന്റെ തീരുമാനമാണ്.",
      },

      grounded: {
        lead: "പ്രസിദ്ധീകരിച്ച രീതിയിലും\nഒരു പാത്തോളജി വകുപ്പിലും മറുപടി ഉറപ്പിച്ചത്.",
      },
      r1: "ഗവ. മെഡിക്കൽ കോളേജ് കോട്ടയം",
      r2: "ASCO/CAP",
      r3: "CVPR 2022",
      r4: "Additive MIL",
      r5: "കൺഫോർമൽ പ്രവചനം",
      r6: "DAB ഡീകൺവോലൂഷൻ",
      r7: "arXiv:2206.01794",
      r8: "PathAI AIM-HER2",

      use: {
        eyebrow: "BioMarkHER2 പ്രായോഗികമായി",
        title: "ഉപയോഗ രീതികൾ",
        body: "അതിർത്തിയിലുള്ള കേസുകൾക്കായി — ത്രെഷോൾഡുകൾക്ക് ഏറ്റവും വിശ്വാസ്യത കുറവുള്ളതും പരിശോധകർ ഏറ്റവും വിയോജിക്കുന്നതുമായ ഫീൽഡുകൾക്കായി.",
        h3: "അതിർത്തിയിലെ 2+",
        p: "അസ്സൽ ഫീൽഡിനു മേൽ മോഡലിന്റെ തീവ്രതാ മാപ്പ് നീക്കാൻ സ്ക്രോൾ ചെയ്യുക. പോർട്ടലിൽ ഇതേ നിയന്ത്രണം വലിച്ചുനീക്കാവുന്ന ഒരു ഹാൻഡിൽ ആണ്; അതിനാൽ മോഡലും ബേസ്‌ലൈനും തമ്മിലുള്ള ഏത് വ്യത്യാസവും ശരാശരിയിൽ മറയാതെ നേരിട്ട് കാണാം.",
        link: "ഫീൽഡ് വിശകലനം തുറക്കുക",
      },

      limits: {
        eyebrow: "ഇതിന് ചെയ്യാനാകാത്തത്",
        title: "മിക്ക ഉപകരണങ്ങളും പറയാതെ വിടുന്ന ഭാഗം.",
        body: "യഥാർഥ പരിമിതികളുള്ള ഒരു ഗവേഷണ പതിപ്പാണിത്. അകത്തെ ഓരോ സ്ക്രീനിലും അവ ഉള്ളതിന്റെ അതേ കാരണത്താൽ അവ ഈ പേജിലുമുണ്ട്: തിരഞ്ഞുപോയി കണ്ടെത്തേണ്ട മുന്നറിയിപ്പ് ആരും കാണില്ല.",
      },
      l1: "ഇത് വിസ്തീർണമാണ് അളക്കുന്നത്, കോശങ്ങളല്ല.",
      l1b: "ശതമാനങ്ങൾ കണ്ടെത്തിയ ടിഷ്യുവിന്റെ പങ്കുകളാണ്. സ്ട്രോമ, ലിംഫോസൈറ്റുകൾ, കൺട്രോൾ ടിഷ്യു എന്നിവ ഛേദത്തിലുണ്ട്. ക്ലിനിക്കൽ നിയമം എണ്ണുന്നത് പൂർണ മെംബ്രെയ്ൻ സ്റ്റെയിനിങ്ങുള്ള ഇൻവേസീവ് ട്യൂമർ കോശങ്ങളെയാണ് — തീർത്തും വ്യത്യസ്തമായ ഒരു അളവ്.",
      l2: "ഒരു പാത്തോളജിസ്റ്റിന്റെ ലേബൽ ഇത് ഒരിക്കലും കണ്ടിട്ടില്ല.",
      l2b: "വിദഗ്ധരുടെ സ്കോറുകൾ ആവർത്തിക്കാനല്ല, ഒപ്റ്റിക്കൽ-ഡെൻസിറ്റി ത്രെഷോൾഡ് നിയമം അനുകരിക്കാനാണ് ഇത് പരിശീലിച്ചത്. ആ നിയമവുമായി വിയോജിക്കുന്നിടത്ത് അത് ശരിയാകാം, തെറ്റാകാം.",
      l3: "2+ ആണ് ഇതിന്റെ ഏറ്റവും ദുർബല വിഭാഗം.",
      l3b: "ഇത് പഠിച്ച ത്രെഷോൾഡുകൾക്ക് ഏറ്റവും വിശ്വാസ്യത കുറവുള്ള ഇടം കൃത്യമായും അതാണ്. 2+ കണക്ക് സൂക്ഷ്മമായി നോക്കാനുള്ള സൂചനയായി കാണുക.",
      l4: "ഒരു ഫീൽഡ് ഒരു കേസ് അല്ല.",
      l4b: "വൈവിധ്യവും സ്റ്റെയിനിങ്ങ് രീതിയും നോക്കി സ്ലൈഡ് തലത്തിൽ എടുക്കുന്ന തീരുമാനമാണ് സ്കോറിങ്. ഇത് ഒരു ഫീൽഡ് മാത്രമേ കാണുന്നുള്ളൂ.",

      final: {
        title: "സ്റ്റെയിൻ എവിടെയാണെന്ന് കാണുക.",
        body: "പോർട്ടൽ തുറന്ന് ഒരു ഫീൽഡ് പരിശോധിക്കുക. താങ്കൾ പ്രവർത്തിപ്പിക്കുന്ന കമ്പ്യൂട്ടറിൽ നിന്ന് ഒന്നും പുറത്തുപോകുന്നില്ല.",
        cta: "പോർട്ടലിലേക്ക് പ്രവേശിക്കുക",
      },
      footer:
        "BioMarkHER2 — കോട്ടയം ഗവൺമെന്റ് മെഡിക്കൽ കോളേജുമായി ചേർന്ന് വികസിപ്പിച്ച അവസാനവർഷ പ്രോജക്ട്. ഗവേഷണത്തിനും ജോലിക്രമ പിന്തുണയ്ക്കും മാത്രം. ഇതൊരു മെഡിക്കൽ ഉപകരണമല്ല; രോഗനിർണയത്തിനായി സാധൂകരിച്ചിട്ടുമില്ല.",
    },

    signup: {
      title: "പോർട്ടൽ പ്രവേശനത്തിന് അപേക്ഷിക്കുക",
      lede:
        "കോട്ടയം ഗവൺമെന്റ് മെഡിക്കൽ കോളേജിലെ പാത്തോളജി വിഭാഗം ജീവനക്കാർക്കായി. ആദ്യ കേസ് നൽകുന്നതിനു മുൻപ് താങ്കളുടെ വിവരങ്ങൾ വകുപ്പിന്റെ രജിസ്റ്ററുമായി ഒത്തുനോക്കും.",
      name: "പൂർണനാമം",
      namePlaceholder: "ഡോ. അനിത മേനോൻ",
      email: "ഔദ്യോഗിക ഇമെയിൽ",
      registration: "മെഡിക്കൽ രജിസ്ട്രേഷൻ നമ്പർ",
      registrationPlaceholder: "TC-MC-24817",
      role: "പദവി",
      password: "പാസ്‌വേഡ്",
      passwordPlaceholder: "കുറഞ്ഞത് 8 അക്ഷരങ്ങൾ",
      confirm: "പാസ്‌വേഡ് ഉറപ്പിക്കുക",
      terms:
        "ഇത് ഒരു ഗവേഷണ ഉപകരണമാണെന്നും മെഡിക്കൽ ഉപകരണമല്ലെന്നും, ഇത് നൽകുന്ന ഓരോ അളവിനും എന്റെ സ്വന്തം വിലയിരുത്തൽ ആവശ്യമാണെന്നും ഞാൻ മനസ്സിലാക്കുന്നു.",
      submit: "അക്കൗണ്ട് ഉണ്ടാക്കുക",
      haveAccount: "നേരത്തെ രജിസ്റ്റർ ചെയ്തിട്ടുണ്ടോ?",
      signIn: "സൈൻ ഇൻ",
      backToSignIn: "സൈൻ ഇൻ പേജിലേക്ക് മടങ്ങുക",
      strength: "പാസ്‌വേഡിന്റെ കരുത്ത്",
      strengthLevels: ["വളരെ ചെറുത്", "ദുർബലം", "സാമാന്യം", "നല്ലത്", "കരുത്തുറ്റത്"],
      errName: "രജിസ്റ്ററിൽ ഉള്ളതുപോലെ പൂർണനാമം നൽകുക.",
      errEmail: "സാധുവായ ഒരു ഇമെയിൽ വിലാസം നൽകുക.",
      errRegistration: "താങ്കളുടെ മെഡിക്കൽ രജിസ്ട്രേഷൻ നമ്പർ നൽകുക.",
      errPassword: "കുറഞ്ഞത് 8 അക്ഷരങ്ങൾ ഉപയോഗിക്കുക; ഒരു അക്ഷരവും ഒരു അക്കവും ഉൾപ്പെടുത്തുക.",
      errConfirm: "രണ്ട് പാസ്‌വേഡുകളും ഒരുപോലെ ആയിരിക്കണം.",
      errTerms: "ഈ ഉപകരണം എന്താണെന്ന് മനസ്സിലാക്കിയതായി സ്ഥിരീകരിക്കുക.",
      emailTaken: "ആ വിലാസത്തിൽ ഈ ബ്രൗസറിൽ ഇതിനകം ഒരു അക്കൗണ്ട് ഉണ്ട്.",
      emailIsDemo: "ആ വിലാസം ഉൾച്ചേർത്ത ഡെമോ അക്കൗണ്ടിന്റേതാണ്. മറ്റൊന്ന് ഉപയോഗിക്കുക.",
      storageBlocked:
        "ഈ ബ്രൗസർ സൈറ്റ് ഡാറ്റ തടയുന്നതിനാൽ അക്കൗണ്ട് സൂക്ഷിക്കാനായില്ല. ഒരു സാധാരണ വിൻഡോയിൽ ശ്രമിക്കുക.",
      noCrypto:
        "ഈ ബ്രൗസറിന് പാസ്‌വേഡ് സുരക്ഷിതമായി ഹാഷ് ചെയ്യാനാകാത്തതിനാൽ അക്കൗണ്ട് ഉണ്ടാക്കിയില്ല. HTTPS-ലോ localhost-ലോ പോർട്ടൽ തുറക്കുക.",
      roles: {
        consultant: "കൺസൾട്ടന്റ് പാത്തോളജിസ്റ്റ്",
        seniorResident: "സീനിയർ റസിഡന്റ്",
        juniorResident: "ജൂനിയർ റസിഡന്റ്",
        technician: "ലബോറട്ടറി ടെക്നീഷ്യൻ",
      },
      posterChip: "വകുപ്പുതല പ്രവേശനം",
      posterTitle: "ഓരോ ഫീൽഡിനും ഒരു പരിശോധകൻ, ഒരു ഒപ്പ്.",
      posterBody:
        "ഈ പോർട്ടലിലൂടെ രേഖപ്പെടുത്തുന്ന ഓരോ വിലയിരുത്തലിലും അത് നടത്തിയ പാത്തോളജിസ്റ്റിന്റെ പേരും രജിസ്ട്രേഷൻ നമ്പറും ഉണ്ടാകും. അളവുകൾ ആ തീരുമാനത്തിനുള്ള ഒരു ഉപാധി മാത്രമാണ് — ഒരിക്കലും അതിനു പകരമല്ല.",
      noticeLead: "ഇത് ഒരു ലോക്കൽ അക്കൗണ്ട് മാത്രമാണ് ഉണ്ടാക്കുന്നത്.",
      noticeBody:
        "ഈ പോർട്ടലിനു പിന്നിൽ ഇതുവരെ ഒരു യൂസർ ഡാറ്റാബേസ് ഇല്ല; അതിനാൽ അക്കൗണ്ട് ഈ ബ്രൗസറിൽ മാത്രമേ നിലനിൽക്കൂ. ഇത് ഒരു അധികാരവും നൽകുന്നില്ല, ഒന്നും പരിശോധിച്ച് ഉറപ്പാക്കുന്നുമില്ല. താങ്കളുടെ പാസ്‌വേഡ് സൂക്ഷിക്കും മുൻപ് സാൾട്ട് ചേർത്ത് ഹാഷ് ചെയ്യുന്നു, അതിനാൽ അത് ഒരിക്കലും പ്ലെയിൻ ടെക്സ്റ്റായി സൂക്ഷിക്കുന്നില്ല — എങ്കിലും ഇതൊരു ഡെമോയായി കണക്കാക്കുക; പ്രധാനപ്പെട്ട ഒരു പാസ്‌വേഡ് ഇവിടെ ആവർത്തിക്കരുത്.",
    },

    dash: {
      lede:
        "ഈ വർക്ക്‌സ്റ്റേഷനിൽ {n} ഫീൽഡുകൾ പരിശോധിച്ചു. അളവുകളും താങ്കളുടെ വിലയിരുത്തലും തമ്മിലുള്ള പൊരുത്തം {pct} ആണ്.",
      ledeOne:
        "ഈ വർക്ക്‌സ്റ്റേഷനിൽ {n} ഫീൽഡ് പരിശോധിച്ചു. അളവുകളും താങ്കളുടെ വിലയിരുത്തലും തമ്മിലുള്ള പൊരുത്തം {pct} ആണ്.",
      ledeNone:
        "ഈ വർക്ക്‌സ്റ്റേഷനിൽ ഇതുവരെ ഒന്നും പരിശോധിച്ചിട്ടില്ല. ലോഗ് തുടങ്ങാൻ ഒരു ഫീൽഡ് വിശകലനം ചെയ്ത് താങ്കളുടെ വിലയിരുത്തൽ രേഖപ്പെടുത്തുക.",
      kpiReviewed: "പരിശോധിച്ച ഫീൽഡുകൾ",
      kpiReviewedFoot: "കഴിഞ്ഞ 7 ദിവസത്തിൽ",
      kpiDelta: "മുൻ 7 ദിവസത്തെ അപേക്ഷിച്ച് · ഈ ആഴ്ച {n}",
      throughputTotal: "14 ദിവസത്തിൽ {n}",
      throughputEmpty: "കഴിഞ്ഞ 14 ദിവസത്തിൽ ഒപ്പുവയ്ക്കലുകളൊന്നുമില്ല.",
      yours: "താങ്കളുടേത്",
      team: "എല്ലാ പരിശോധകരും",
      thisWeek: "ഈ ആഴ്ച",
      recentSubDemo: "ഡെമോ ചരിത്രം — ബാക്കെൻഡ് പ്രവർത്തിക്കുന്നില്ല",
      kpiConcordant: "അളവുകൾ പൊരുത്തപ്പെട്ടത്",
      kpiConcordantFoot: "{b} ഒപ്പുവയ്ക്കലുകളിൽ {a} എണ്ണം മാപ്പുകളോട് യോജിച്ചു",
      kpiFlagged: "വ്യത്യാസം രേഖപ്പെടുത്തിയവ",
      kpiFlaggedFoot: "മാപ്പുകൾ ഫീൽഡുമായി പൊരുത്തപ്പെടുന്നില്ലെന്ന് പരിശോധകൻ രേഖപ്പെടുത്തി",
      kpiUnassessable: "വിലയിരുത്താനാകാത്തവ",
      kpiUnassessableFoot: "ഫീൽഡിൽ ഇൻവേസീവ് ട്യൂമർ പര്യാപ്തമല്ല",
      benchOn: "പരിശോധനയിലുള്ള ഫീൽഡ്",
      benchOff: "പരിശോധനയിൽ ഒന്നുമില്ല",
      benchSubOn: "{id} · {w}×{h}",
      benchSubOff:
        "ഒരു ഫീൽഡ് ലോഡ് ചെയ്താൽ അതിന്റെ തീവ്രതാ മാപ്പും വിസ്തീർണ അളവുകളും ഇവിടെ കാണാം.",
      benchEmpty:
        "പരിശീലന ഡാറ്റാസെറ്റിൽ നിന്ന് ഒരു ഉദാഹരണ പാച്ച് തിരഞ്ഞെടുക്കുക, അല്ലെങ്കിൽ സ്വന്തം IHC ഫീൽഡ് ഇവിടെ ഇടുക. ഒന്നും എവിടേക്കും അപ്‌ലോഡ് ചെയ്യുന്നില്ല.",
      chooseField: "ഒരു ഫീൽഡ് തിരഞ്ഞെടുക്കുക",
      open: "തുറക്കുക",
      start: "തുടങ്ങുക",
      largestClass: "ഏറ്റവും കൂടുതൽ വിസ്തീർണമുള്ള തീവ്രതാ വിഭാഗം",
      measurementNotScore: "കണ്ടെത്തിയ ടിഷ്യുവിന്റെ {pct} — ഇതൊരു അളവാണ്, സ്കോർ അല്ല",
      throughput: "പരിശോധനയുടെ തോത്",
      throughputSub: "കഴിഞ്ഞ 14 ദിവസത്തിൽ ദിവസേന ഒപ്പുവച്ച ഫീൽഡുകൾ",
      recent: "സമീപകാല ഒപ്പുവയ്ക്കലുകൾ",
      recentSub: "സെർവറിന്റെ റിവ്യൂ ലോഗിൽ നിന്ന്, ഏറ്റവും പുതിയത് ആദ്യം",
      viewAll: "എല്ലാം കാണുക",
      noneRecorded: "ഇതുവരെ വിലയിരുത്തലുകളൊന്നും രേഖപ്പെടുത്തിയിട്ടില്ല.",
      signOffs: "ഒപ്പുവയ്ക്കലുകൾ",
      flagged: "വ്യത്യാസമുള്ളവ",
      mix: "വിലയിരുത്തലുകളുടെ വിതരണം",
      mixSub: "പരിശോധകർ നൽകിയ സ്കോറുകൾ",
      concordance: "പൊരുത്തം",
      concordanceSub: "പരിശോധകൻ മാപ്പുകളോട് യോജിച്ചു",
      concordanceNote:
        "ഇവിടെ പൊരുത്തം എന്നാൽ “ഞാൻ കാണുന്നതുമായി അളവുകൾ യോജിക്കുന്നു” എന്ന് പരിശോധകൻ രേഖപ്പെടുത്തി എന്നു മാത്രമാണ്. ഇത് കൃത്യതയുടെ അളവല്ല: പാത്തോളജിസ്റ്റുകളുടെ ലേബലുകൾ ഉപയോഗിച്ച് ഈ മോഡലിനെ ഒരിക്കലും പരിശീലിപ്പിച്ചിട്ടില്ല.",
      deployment: "വിന്യാസം",
      deploymentSub: "ഇപ്പോൾ പ്രതികരിക്കുന്നത് ഏതാണ്",
      source: "സ്രോതസ്സ്",
      sourceDemo: "ഡെമോ ഡാറ്റ (ബാക്കെൻഡിലേക്ക് എത്താനാകുന്നില്ല)",
      sourceLive: "ലൈവ് ബാക്കെൻഡ്",
      analyseField: "ഒരു ഫീൽഡ് വിശകലനം ചെയ്യുക",
      caseLog: "കേസ് രേഖ",
    },

    table: {
      field: "ഫീൽഡ്",
      assessment: "വിലയിരുത്തൽ",
      datasetLabel: "ഡാറ്റാസെറ്റ് ലേബൽ",
      tissue: "ടിഷ്യു",
      reviewer: "പരിശോധകൻ",
      concordant: "പൊരുത്തം",
      notes: "കുറിപ്പുകൾ",
      recorded: "രേഖപ്പെടുത്തിയത്",
      when: "എപ്പോൾ",
      flagged: "വ്യത്യാസം",
      intensityClass: "തീവ്രതാ വിഭാഗം",
      model: "മോഡൽ",
      baseline: "ത്രെഷോൾഡ് ബേസ്‌ലൈൻ",
      difference: "വ്യത്യാസം",
      share: "പങ്ക്",
    },

    analysis: {
      steps: "ഘട്ടം 1 · ഫീൽഡ് തിരഞ്ഞെടുക്കുക  ·  ഘട്ടം 2 · പരിശോധിക്കുക",
      title: "ഫീൽഡ് വിശകലനം",
      lede:
        "ഒരു IHC ഫീൽഡ് മോഡലിലൂടെയും ത്രെഷോൾഡ് ബേസ്‌ലൈനിലൂടെയും ഒരുമിച്ച് കടത്തിവിടുക; തുടർന്ന് താങ്കൾ കാണുന്നതുമായി തട്ടിച്ചുനോക്കി സ്വന്തം വിലയിരുത്തൽ രേഖപ്പെടുത്തുക.",
      pdfReport: "PDF റിപ്പോർട്ട്",
      analyse: "ഫീൽഡ് വിശകലനം ചെയ്യുക",
      source: "ഫീൽഡിന്റെ ഉറവിടം",
      upload: "അപ്‌ലോഡ്",
      samplePatch: "പരിശീലന ഡാറ്റാസെറ്റിൽ നിന്നുള്ള ഉദാഹരണ പാച്ച്",
      noSamples: "ഉദാഹരണ പാച്ചുകളൊന്നും കണ്ടെത്തിയില്ല",
      sampleHint:
        "ഡാറ്റാസെറ്റ് പാച്ച് ലേബൽ: {label}. താരതമ്യത്തിനായി മാത്രം കാണിക്കുന്നു — ഇത് ഡാറ്റാസെറ്റിന്റെ സ്വന്തം ലേബലാണ്, ഈ ഫീൽഡിനെക്കുറിച്ചുള്ള ഒരു പാത്തോളജിസ്റ്റിന്റെ വിലയിരുത്തലല്ല.",
      or: "അല്ലെങ്കിൽ",
      dropTitle: "ഒരു IHC ഫീൽഡ് ഇവിടെ ഇടുക, അല്ലെങ്കിൽ തിരഞ്ഞെടുക്കുക",
      dropSub: "PNG, JPEG അല്ലെങ്കിൽ TIFF · ഈ കമ്പ്യൂട്ടറിൽ തന്നെ സൂക്ഷിക്കുന്നു, ഒന്നും അപ്‌ലോഡ് ചെയ്യുന്നില്ല",
      clearUpload: "അപ്‌ലോഡ് മായ്ക്കുക",
      keyResult: "പ്രധാന ഫലം",
      measurement: "അളവ്",
      largestClass: "ഏറ്റവും കൂടുതൽ വിസ്തീർണമുള്ള തീവ്രതാ വിഭാഗം",
      sourceLabel: "ഈ ഫീൽഡിന്റെ ഡാറ്റാസെറ്റ് ലേബൽ {label} ആണ്",
      pickClassLabel: "ഈ ഫീൽഡിന് ഡാറ്റാസെറ്റ് ലേബൽ ഇല്ല — പരിശോധിക്കാൻ ഒരു വിഭാഗം തിരഞ്ഞെടുക്കുക",
      classPickerLabel: "പരിശോധിക്കാനുള്ള തീവ്രതാ വിഭാഗം",
      ofTissue: "കണ്ടെത്തിയ ടിഷ്യുവിന്റെ {pct}",
      seeWhere: "ഈ വിഭാഗം എവിടെയാണെന്ന് കാണുക",
      notAScoreLead: "ഇത് ഒരു HER2 സ്കോർ",
      notAScoreBold: "അല്ല",
      notAScoreRest:
        ". തിരഞ്ഞെടുത്ത തീവ്രതാ വിഭാഗത്തിൽ ഈ ഫീൽഡിന്റെ എത്ര ടിഷ്യു വിസ്തീർണം ഉൾപ്പെടുന്നു എന്നാണിത്. കേസ് സ്കോർ ചെയ്യേണ്ടത് താങ്കൾ തന്നെയാണ്.",
      heatLegend: "DAB ഒപ്റ്റിക്കൽ ഡെൻസിറ്റി",
      heatLow: "സ്റ്റെയിൻ ഇല്ല",
      tissueCoverage: "ടിഷ്യുവിന്റെ വ്യാപ്തി",
      tissueCoverageNote:
        "ഈ {w}×{h} ഫീൽഡിന്റെ {pct} ടിഷ്യുവാണ്. മുകളിലുള്ള ഓരോ ശതമാനവും ആ വിസ്തീർണത്തിന്റെ പങ്കാണ് — ട്യൂമർ കോശങ്ങളുടെ പങ്കല്ല.",
      supporting: "അനുബന്ധ ഫലങ്ങൾ",
      disagreement: "മോഡലും ബേസ്‌ലൈനും തമ്മിലുള്ള വ്യത്യാസം",
      disagreementHint: "രണ്ട് രീതികളും വ്യത്യസ്ത വിഭാഗത്തിൽ ഉൾപ്പെടുത്തിയ ടിഷ്യു പിക്സലുകൾ",
      ambiguous: "α={alpha}-ൽ അവ്യക്തമായവ",
      ambiguousHint: "കാലിബ്രേറ്റ് ചെയ്ത പ്രവചനഗണത്തിൽ ഒന്നിലധികം വിഭാഗങ്ങളുണ്ട്",
      staleCalibration:
        "ഇപ്പോൾ ലോഡ് ചെയ്തിരിക്കുന്നതിൽ നിന്ന് വ്യത്യസ്തമായ ഒരു ചെക്ക്‌പോയിന്റിനെതിരെയാണ് ഈ കാലിബ്രേഷൻ കണക്കാക്കിയത് — അതിനാൽ അവ്യക്തതയുടെ കണക്കുകൾ പ്രവർത്തിക്കുന്ന മോഡലിനെ പ്രതിഫലിപ്പിച്ചേക്കില്ല. വീണ്ടും പ്രവർത്തിപ്പിക്കുക:",
      signoff: "പാത്തോളജിസ്റ്റിന്റെ ഒപ്പ്",
      yourAssessment: "ഈ ഫീൽഡിന്റെ HER2 സ്കോർ — താങ്കളുടെ വിലയിരുത്തൽ",
      cannotAssess: "വിലയിരുത്താനാകില്ല",
      agrees: "മുകളിലുള്ള അളവുകൾ ഞാൻ കാണുന്നതുമായി യോജിക്കുന്നു",
      notesLabel: "കുറിപ്പുകൾ (നിർബന്ധമല്ല)",
      notesPlaceholder:
        "മെംബ്രെയ്ൻ പൂർണത, സ്റ്റെയിനിങ് രീതി, ആർട്ടിഫാക്ടുകൾ — തീവ്രതാ മാപ്പിൽ വരാത്ത എന്തും",
      signingAs: "ഒപ്പിടുന്നത്",
      record: "എന്റെ വിലയിരുത്തൽ രേഖപ്പെടുത്തുക",
      compare: "താരതമ്യം",
      compareTitle: "മോഡൽ മാപ്പും ത്രെഷോൾഡ് ബേസ്‌ലൈനും തമ്മിൽ തട്ടിച്ചുനോക്കുക",
      enlarge: "വലുതാക്കുക",
      layers: "ചിത്ര പാളികൾ",
      emptyTitle: "ഒരു ഫീൽഡും ലോഡ് ചെയ്തിട്ടില്ല",
      emptyBody:
        "ഇടതുവശത്ത് ഒരു ഉദാഹരണ പാച്ച് തിരഞ്ഞെടുക്കുക അല്ലെങ്കിൽ ഒരു IHC ചിത്രം ഇടുക, തുടർന്ന് വിശകലനം നടത്തുക. ഒന്നും ഈ കമ്പ്യൂട്ടറിൽ നിന്ന് പുറത്തുപോകുന്നില്ല.",
      tableTitle: "കണ്ടെത്തിയ ടിഷ്യുവിന്റെ ശതമാനമായി സ്റ്റെയിൻ ചെയ്ത വിസ്തീർണം",
      tableSub:
        "ഇത് ട്യൂമർ കോശങ്ങളുടെ ശതമാനമല്ല. സ്ട്രോമ, ലിംഫോസൈറ്റുകൾ, സാധാരണ ഡക്ടുകൾ, കൺട്രോൾ ടിഷ്യു എന്നിവയെല്ലാം ഈ ഛേദത്തിനുള്ളിലുണ്ട്.",
      leastReliable: "ഏറ്റവും കുറഞ്ഞ വിശ്വാസ്യത",
      summary: "ടിഷ്യു പിക്സലുകളുടെ {pct} കാര്യത്തിൽ മോഡലും ബേസ്‌ലൈനും വിയോജിക്കുന്നു.",
      summaryConformal:
        " α={alpha} എന്ന സാർഥകതാ തലത്തിൽ, ടിഷ്യു പിക്സലുകളുടെ {pct} അവ്യക്തമായ പ്രവചനഗണമുള്ളവയാണ്.",
      caveatsTitle: "ഈ സംഖ്യകൾ എന്താണ്, എന്തല്ല",
      caveatsSub: "PDF റിപ്പോർട്ടിൽ അതേപടി വീണ്ടും ചേർക്കുന്നു",
      fullMethod: "പൂർണ രീതി",
      compareCaption: "മോഡൽ തീവ്രതാ മാപ്പും ത്രെഷോൾഡ് ബേസ്‌ലൈനും",
      compareNote:
        "ഹാൻഡിൽ വലിച്ചുനീക്കുക. ഇടതുവശം മോഡൽ; വലതുവശം പരമ്പരാഗത ത്രെഷോൾഡ് നിയമം. ഇവ വ്യത്യാസപ്പെടുന്നിടത്ത്, മോഡൽ അതിന്റെ സ്യൂഡോ-ലേബലുകൾക്കപ്പുറം സാമാന്യവൽക്കരിക്കുകയാണ് — അത് ശരിയാകാം, തെറ്റാകാം.",
      modelNote: "{arch}, ത്രെഷോൾഡ് സ്യൂഡോ-ലേബലുകൾ ഉപയോഗിച്ച് പരിശീലിപ്പിച്ചത്. പശ്ചാത്തലം നിറം നൽകാതെ വിട്ടിരിക്കുന്നു.",
      theModel: "മോഡൽ",
      views: {
        original: "അസ്സൽ ചിത്രം",
        originalNote: "സ്കാൻ ചെയ്തതുപോലെ, ഒരു സംസ്കരണവും നടത്തും മുൻപ്.",
        tissue: "ടിഷ്യു മാസ്ക്",
        tissueNote:
          "ഈ മാസ്കിനു പുറത്തുള്ളതെല്ലാം വശത്തെ ശതമാനക്കണക്കുകളിൽ നിന്ന് ഒഴിവാക്കിയിരിക്കുന്നു.",
        model: "തീവ്രതാ മാപ്പ്",
        isolate: "എവിടെ: {label}",
        isolateNote:
          "തിരഞ്ഞെടുത്ത തീവ്രതാ വിഭാഗം മാത്രം നിറം നൽകിയിരിക്കുന്നു; മറ്റെല്ലാ വിഭാഗങ്ങളും പശ്ചാത്തലവും സ്കാൻ ചെയ്തതുപോലെ കാണിക്കുന്നു — തിരക്കേറിയ ഒരു ഫീൽഡിൽ ചെറിയ പങ്കുള്ള ഒരു വിഭാഗം പോലും എളുപ്പത്തിൽ കണ്ടെത്താൻ.",
        heatmap: "DAB ഹീറ്റ്മാപ്പ്",
        heatmapNote:
          "തീവ്രതാ മാപ്പിലെ അതേ DAB സിഗ്നൽ, നാലു വിഭാഗങ്ങളിലേക്ക് വേർതിരിക്കാതെ — അതിർത്തിയിലുള്ള ഒരു പിക്സൽ ഒരു വിഭാഗത്തിലേക്ക് നിർബന്ധിക്കപ്പെടുന്നതിനു പകരം രണ്ട് വിഭാഗങ്ങൾക്കിടയിലുള്ള ഒരു നിറമായി കാണപ്പെടുന്നു.",
        baseline: "ത്രെഷോൾഡ് ബേസ്‌ലൈൻ",
        baselineNote:
          "പരമ്പരാഗത DAB ഒപ്റ്റിക്കൽ-ഡെൻസിറ്റി ത്രെഷോൾഡുകൾ — മോഡൽ അനുകരിക്കാൻ പരിശീലിപ്പിക്കപ്പെട്ട നിയമം.",
        ambiguity: "വിശ്വാസ്യത",
        ambiguityNote:
          "മോഡലിന്റെ കാലിബ്രേറ്റ് ചെയ്ത പ്രവചനഗണം ഒറ്റ വിഭാഗത്തിലേക്ക് ചുരുങ്ങുന്നിടം (ഉറപ്പ്) ഒന്നിലധികം വിഭാഗങ്ങൾ ഉള്ളിടം (അവ്യക്തം) എന്നിവ. ഇത് വിശ്വാസ്യതാ മാപ്പാണ്, വിഭാഗ മാപ്പല്ല.",
      },
      tabs: {
        original: "അസ്സൽ",
        tissue: "ടിഷ്യു",
        model: "തീവ്രത",
        isolate: "എവിടെ {label}",
        heatmap: "ഹീറ്റ്മാപ്പ്",
        baseline: "ബേസ്‌ലൈൻ",
        ambiguity: "വിശ്വാസ്യത",
      },
      annotate: {
        title: "ഫീൽഡ് അടയാളക്കുറിപ്പുകൾ",
        listSub: "മുകളിലെ ചിത്രത്തിൽ അടയാളപ്പെടുത്തിയ ഭാഗങ്ങൾ, സംരക്ഷിച്ച ക്രമത്തിൽ",
        hint: "ഒരു ഭാഗം അടയാളപ്പെടുത്താൻ ചിത്രത്തിൽ വലിക്കുക",
        toggle: "അടയാളപ്പെടുത്തുക",
        done: "കഴിഞ്ഞു",
        toggleTitle: "ഫീൽഡിൽ ഭാഗങ്ങൾ അടയാളപ്പെടുത്തുക — നിർത്താൻ Esc",
        notePlaceholder: "ഇവിടെ എന്താണ് ശ്രദ്ധയിൽപ്പെട്ടത്?",
        cancel: "റദ്ദാക്കുക",
        save: "അടയാളക്കുറിപ്പ് സംരക്ഷിക്കുക",
        savedTitle: "അടയാളക്കുറിപ്പ് സംരക്ഷിച്ചു",
        savedLive: "സെർവർ-സൈഡ് ലോഗിൽ എഴുതി.",
        savedDemo: "ഈ സെഷനിൽ മാത്രം സൂക്ഷിച്ചു — ബാക്കെൻഡ് പ്രവർത്തിക്കുന്നില്ല.",
        failedTitle: "അടയാളക്കുറിപ്പ് സംരക്ഷിക്കാനായില്ല",
      },
    },

    cases: {
      eyebrow: "ഒപ്പുവയ്ക്കലുകളുടെ ചരിത്രം",
      title: "കേസ് രേഖ",
      demoRows: "ഡെമോ ചരിത്രം",
      lede:
        "ഈ വർക്ക്‌സ്റ്റേഷനിൽ നിന്ന് രേഖപ്പെടുത്തിയ എല്ലാ വിലയിരുത്തലുകളും. {path} എഴുതുന്ന സെർവറിലെ JSONL രേഖയാണ് ആധികാരിക രേഖ; ഇത് അതിന്റെ സൗകര്യപ്രദമായ കാഴ്ചയാണ്.",
      all: "എല്ലാം",
      flagged: "വ്യത്യാസമുള്ളവ",
      concordant: "പൊരുത്തമുള്ളവ",
      unassessable: "വിലയിരുത്താനാകാത്തവ",
      filterLabel: "വിലയിരുത്തലുകൾ അരിച്ചെടുക്കുക",
      search: "പാച്ച്, പരിശോധകൻ അല്ലെങ്കിൽ കുറിപ്പ് തിരയുക",
      searchLabel: "വിലയിരുത്തലുകൾ തിരയുക",
      emptyTitle: "ഇതുമായി ഒന്നും പൊരുത്തപ്പെടുന്നില്ല",
      emptyBody: "തിരച്ചിൽ മായ്ക്കുക, അല്ലെങ്കിൽ മറ്റൊരു ഫിൽട്ടർ തിരഞ്ഞെടുക്കുക.",
      footnote:
        "“പൊരുത്തം” എന്നത് <i>ഞാൻ കാണുന്നതുമായി അളവുകൾ യോജിക്കുന്നു</i> എന്ന് പരിശോധകൻ രേഖപ്പെടുത്തിയോ എന്നു മാത്രമാണ് സൂചിപ്പിക്കുന്നത്. ഇത് മോഡലിന്റെ കൃത്യതയുടെ അളവല്ല: ഒപ്റ്റിക്കൽ-ഡെൻസിറ്റി സ്യൂഡോ-ലേബലുകൾ ഉപയോഗിച്ചാണ് മോഡൽ പരിശീലിച്ചത്; ഒരു പാത്തോളജിസ്റ്റിന്റെ ലേബൽ അത് ഒരിക്കലും കണ്ടിട്ടില്ല.",
    },

    model: {
      eyebrow: "രേഖകൾ",
      title: "മോഡൽ കാർഡ്",
      lede:
        "വിന്യസിച്ച ചെക്ക്‌പോയിന്റ് എന്താണ്, അത് എന്തിൽ നിന്ന് പഠിച്ചു, അതിനു ചെയ്യാനാകാത്ത നാല് കാര്യങ്ങൾ ഏതൊക്കെ.",
      spec: "വിശദാംശങ്ങൾ",
      specSub: "ഈ വിന്യാസം",
      limitations: "അറിയപ്പെടുന്ന പരിമിതികൾ",
      limitationsSub: "ഈ ഉപകരണത്തിൽ നിന്നുള്ള ഏതെങ്കിലും കണക്ക് ഉദ്ധരിക്കും മുൻപ് ഇവ വായിക്കുക",
      comparison: "താരതമ്യത്തിന് — അംഗീകാരം ലഭിച്ച ഒരു വാണിജ്യ സംവിധാനം",
      comparisonSub:
        "PathAI AIM-HER2 Breast Cancer. ഇത് മറ്റൊരു കമ്പനിയുടെ ഉൽപ്പന്നമാണ്; ഈ മേഖലയിൽ സാധൂകരിക്കപ്പെട്ട ഒരു സംവിധാനം എങ്ങനെയിരിക്കും എന്നു കാണിക്കാൻ മാത്രം ഇവിടെ ചേർത്തിരിക്കുന്നു. അതിന്റെ പ്രകടനത്തിലൊന്നും ഈ പ്രോജക്ടിന് അവകാശമില്ല.",
      comparisonNote:
        "പ്രധാന വ്യത്യാസം: AIM-HER2 സ്ലൈഡ് തലത്തിലുള്ള സ്കോർ പ്രവചിക്കുന്നു; ബോർഡ് സർട്ടിഫൈഡ് പാത്തോളജിസ്റ്റുകളുടെ വിലയിരുത്തലുകൾ ഉപയോഗിച്ചാണ് അത് പരിശീലിച്ചത്. ഈ പ്രോജക്ട് ത്രെഷോൾഡ് സ്യൂഡോ-ലേബലുകളിൽ നിന്ന് പിക്സൽ തലത്തിലുള്ള സ്റ്റെയിൻ തീവ്രത പ്രവചിക്കുന്നു, ഒരു സ്കോർ നൽകാൻ ബോധപൂർവം വിസമ്മതിക്കുകയും ചെയ്യുന്നു.",
      checkpoint: "വിന്യസിച്ച ചെക്ക്‌പോയിന്റ്",
      checkpointSub: "ലോഡ് ചെയ്യുമ്പോൾ സെർവർ അറിയിക്കുന്നത്",
      checkpointLabel: "ചെക്ക്‌പോയിന്റ്",
      trained: "പരിശീലിപ്പിച്ചത്",
      demoWarning:
        "ബാക്കെൻഡിലേക്ക് എത്താനാകുന്നില്ല, അതിനാൽ ഈ വിവരങ്ങൾ ഡെമോ മൊഡ്യൂളിൽ നിന്നുള്ള താൽക്കാലിക മൂല്യങ്ങളാണ് — പ്രവർത്തിക്കുന്ന ഒരു ചെക്ക്‌പോയിന്റിന്റേതല്ല.",
      classes: "തീവ്രതാ വിഭാഗങ്ങൾ",
      classesSub: "സെർവർ നൽകുന്ന വർണനിര",
      classIndex: "സൂചിക {i} · {color}",
      classesNote:
        "ലെജൻഡും തീവ്രതാ മാപ്പും ഫലപ്പട്ടികയും ഇതേ വർണനിര തന്നെയാണ് വായിക്കുന്നത്, അതിനാൽ അവ തമ്മിൽ ഒരിക്കലും വ്യത്യാസം വരില്ല. DAB ഹീറ്റ്മാപ്പിന് സ്വന്തം ഹീറ്റ് സ്കെയിൽ ഉണ്ട്, അതേ മൂന്ന് ത്രെഷോൾഡുകളിൽ ഉറപ്പിച്ചത്:",
      specs: {
        intendedUse: "ഉദ്ദേശിച്ച ഉപയോഗം",
        intendedUseBody:
          "ഗവേഷണത്തിനും ജോലിക്രമ പിന്തുണയ്ക്കും മാത്രം. ഇതൊരു മെഡിക്കൽ ഉപകരണമല്ല; രോഗനിർണയത്തിനായി സാധൂകരിച്ചിട്ടില്ല.",
        task: "ദൗത്യം",
        taskBody:
          "കണ്ടെത്തിയ ടിഷ്യുവിന് മേൽ പിക്സൽ തലത്തിലുള്ള സ്റ്റെയിൻ-തീവ്രതാ വിഭജനം. കേസ് തലത്തിലുള്ള HER2 സ്കോർ മോഡൽ നൽകുന്നില്ല.",
        indication: "സൂചന",
        indicationBody: "സ്തനാർബുദ HER2 ഇമ്യൂണോഹിസ്റ്റോകെമിസ്ട്രി",
        inputs: "ഇൻപുട്ടുകൾ",
        inputsBody:
          "PNG, JPEG അല്ലെങ്കിൽ TIFF രൂപത്തിലുള്ള ഒറ്റ IHC ഫീൽഡ്. മുഴുവൻ സ്ലൈഡ് ചിത്രങ്ങൾ പിന്തുണയ്ക്കുന്നില്ല.",
        outputs: "ഔട്ട്പുട്ടുകൾ",
        outputsBody:
          "ടിഷ്യു മാസ്ക്; നാല് വിഭാഗ തീവ്രതാ മാപ്പ്; കണ്ടെത്തിയ ടിഷ്യുവിന്റെ ശതമാനമായി ഓരോ വിഭാഗത്തിന്റെയും സ്റ്റെയിൻ വിസ്തീർണം; കാലിബ്രേഷൻ ലോഡ് ചെയ്തിട്ടുണ്ടെങ്കിൽ കൺഫോർമൽ പ്രവചനഗണ അവ്യക്തതാ മാപ്പ്.",
        targets: "പരിശീലന ലക്ഷ്യങ്ങൾ",
        targetsBody:
          "പരമ്പരാഗത DAB ഒപ്റ്റിക്കൽ-ഡെൻസിറ്റി ത്രെഷോൾഡുകളിൽ നിന്ന് ഉരുത്തിരിഞ്ഞ സ്യൂഡോ-ലേബലുകൾ. പാത്തോളജിസ്റ്റുകളുടെ അടയാളപ്പെടുത്തലുകൾ ഉപയോഗിച്ചിട്ടില്ല.",
        site: "വികസന കേന്ദ്രം",
        siteBody: "കോട്ടയം ഗവൺമെന്റ് മെഡിക്കൽ കോളേജ്",
      },
      ref: {
        intendedUse: "ഉദ്ദേശിച്ച ഉപയോഗം",
        intendedUseBody: "ഗവേഷണ ഉപയോഗത്തിനു മാത്രം",
        outputs: "ഔട്ട്പുട്ടുകൾ",
        outputsBody:
          "HER2 സ്കോർ (0, 1+, 2+, 3+); ഇൻവേസീവ് കാർസിനോമയുടെ വിസ്തീർണം; അഡിറ്റീവ് മൾട്ടിപ്പിൾ-ഇൻസ്റ്റൻസ് ലേണിങ് (aMIL) ഡെൻസിറ്റി ഹീറ്റ്‌മാപ്പ്",
        clones: "ക്ലോണുകൾ",
        clonesBody: "Ventana 4B5, Dako HercepTest",
        scanners: "സ്കാനറുകൾ",
        scannersBody: "Leica Aperio AT2, GT450; Hamamatsu NanoZoomer s360",
        inputs: "ഇൻപുട്ടുകൾ",
        inputsBody:
          "പ്രാഥമിക, ആവർത്തിത അല്ലെങ്കിൽ മെറ്റാസ്റ്റാറ്റിക് ട്യൂമറിൽ നിന്നുള്ള മുഴുവൻ സ്ലൈഡ് ബയോപ്സി, റിസെക്ഷൻ അല്ലെങ്കിൽ എക്സിഷൻ; ഇൻ-സൈറ്റു ട്യൂമർ ഒഴികെ",
        reference: "അവലംബം",
      },
      limits: {
        areaTitle: "ഇത് വിസ്തീർണമാണ് അളക്കുന്നത്, കോശങ്ങളല്ല",
        areaBody:
          "ശതമാനങ്ങൾ കണ്ടെത്തിയ ടിഷ്യു വിസ്തീർണത്തിന്റെ പങ്കുകളാണ്. സ്ട്രോമ, ലിംഫോസൈറ്റുകൾ, സാധാരണ ഡക്ടുകൾ, കൺട്രോൾ ടിഷ്യു എന്നിവയെല്ലാം ഛേദത്തിനുള്ളിലാണ്. ക്ലിനിക്കൽ നിയമം എണ്ണുന്നത് പൂർണമായ മെംബ്രെയ്ൻ സ്റ്റെയിനിങ്ങുള്ള ഇൻവേസീവ് ട്യൂമർ കോശങ്ങളെയാണ് — അത് വേറൊരു അളവാണ്, വേറൊരു കൂട്ടത്തിന് മേൽ കണക്കാക്കുന്നതും.",
        twoTitle: "2+ വിഭാഗമാണ് ഏറ്റവും ദുർബലം",
        twoBody:
          "ഒപ്റ്റിക്കൽ-ഡെൻസിറ്റി ത്രെഷോൾഡുകൾക്ക് ഏറ്റവും വിശ്വാസ്യത കുറവുള്ളത് കൃത്യമായും 2+ എന്നിടത്താണ്; ഈ മോഡൽ പഠിച്ചതാകട്ടെ ത്രെഷോൾഡുകളിൽ നിന്നു മാത്രവും. ഒരു 2+ വിസ്തീർണക്കണക്ക് സൂക്ഷ്മമായി നോക്കാനുള്ള സൂചനയായി കാണുക, ഉദ്ധരിക്കാനുള്ള സംഖ്യയായിട്ടല്ല.",
        labelTitle: "ഒരു പാത്തോളജിസ്റ്റിന്റെ ലേബൽ ഇത് ഒരിക്കലും കണ്ടിട്ടില്ല",
        labelBody:
          "ഒരു ത്രെഷോൾഡ് നിയമം അനുകരിക്കാനാണ് മോഡലിനെ പരിശീലിപ്പിച്ചത്. ബേസ്‌ലൈനുമായി അത് വിയോജിക്കുന്നിടത്ത് അത് സാമാന്യവൽക്കരണമാണ് — അത് ഒരു മെച്ചപ്പെടുത്തലാകാം, ഒരു പിഴവുമാകാം. വ്യത്യാസം ശരാശരിയിൽ മറയാതിരിക്കാൻ രണ്ട് നിരകളും അടുത്തടുത്ത് കാണിക്കുന്നു.",
        fieldTitle: "ഒരു ഫീൽഡ് ഒരു കേസ് അല്ല",
        fieldBody:
          "വൈവിധ്യം, മെംബ്രെയ്ൻ പൂർണത, സ്റ്റെയിനിങ് രീതി എന്നിവ നോക്കി സ്ലൈഡ് തലത്തിലും കേസ് തലത്തിലും എടുക്കുന്ന തീരുമാനമാണ് സ്കോറിങ്. ഈ ഉപകരണം ഒരു സമയം ഒരു ഫീൽഡ് മാത്രമാണ് കാണുന്നത്; സ്ലൈഡിന്റെ ബാക്കി ഭാഗം അതിന്റെ കാഴ്ചയിലില്ല.",
      },
    },

    method: {
      eyebrow: "രേഖകൾ",
      title: "രീതിയും മുന്നറിയിപ്പുകളും",
      lede:
        "വിശകലന സ്ക്രീനിലെ സംഖ്യകൾ എന്താണ്, അതിലേറെ പ്രധാനമായി — അവ എന്തല്ല.",
      caveatsTitle: "ഈ സംഖ്യകൾ എന്താണ്, എന്തല്ല",
      caveatsSub: "ഓരോ വിശകലനത്തിനൊപ്പവും നൽകുന്നു, ഓരോ PDF റിപ്പോർട്ടിലും വീണ്ടും ചേർക്കുന്നു",
      pipeline: "ഒരു ഫീൽഡ് എങ്ങനെ സംസ്കരിക്കുന്നു",
      pipelineSub: "അഞ്ച് ഘട്ടങ്ങൾ, ഒന്നും ഒരു സ്കോർ ഉണ്ടാക്കുന്നില്ല",
      step: "ഘട്ടം {n}",
      notDeviceLead: "ഇതൊരു മെഡിക്കൽ ഉപകരണമല്ല.",
      notDeviceBody:
        "കോട്ടയം ഗവൺമെന്റ് മെഡിക്കൽ കോളേജുമായി ചേർന്ന് വികസിപ്പിച്ച ഒരു അവസാനവർഷ പ്രോജക്ടാണ് BioMarkHER2; ഗവേഷണത്തിനും ജോലിക്രമ പിന്തുണയ്ക്കും വേണ്ടിയുള്ളത്. രോഗനിർണയത്തിനായി ഇത് സാധൂകരിച്ചിട്ടില്ല; ഇതു മാത്രം ആശ്രയിച്ച് ഒരു ക്ലിനിക്കൽ തീരുമാനം എടുക്കരുത്.",
      dataTitle: "ഡാറ്റ കൈകാര്യം ചെയ്യൽ",
      dataSub: "ചിത്രങ്ങൾ എവിടെ പോകുന്നു",
      refTitle: "അവലംബം",
      refSub: "പശ്ചാത്തല വായന",
      caveatTitles: {
        not_a_score: "ഈ ഉപകരണം എന്താണ്",
        denominator: "ഈ ശതമാനം ആരുടേതാണ്",
        targets: "മോഡൽ എന്തിൽ നിന്ന് പഠിച്ചു",
        model_limitation: "2+ വിഭാഗം",
      },
      steps: {
        detectTitle: "ടിഷ്യു കണ്ടെത്തുക",
        detectBody:
          "ഒരു ടിഷ്യു മാസ്ക് സെക്ഷനെ സ്ലൈഡിന്റെ പശ്ചാത്തലത്തിൽ നിന്ന് വേർതിരിക്കുന്നു. അതിനു പുറത്തുള്ളതെല്ലാം ഉപകരണം നൽകുന്ന എല്ലാ ശതമാനക്കണക്കുകളിൽ നിന്നും ഒഴിവാക്കുന്നു.",
        classifyTitle: "സ്റ്റെയിൻ തീവ്രത തരംതിരിക്കുക",
        classifyBody:
          "ഓരോ ടിഷ്യു പിക്സലിനും നാല് DAB തീവ്രതാ വിഭാഗങ്ങളിൽ ഒന്ന് നൽകുന്നു. ഇത് പിക്സൽ തലത്തിലുള്ള വിഭജനമാണ്; കോശ തലത്തിലോ മെംബ്രെയ്ൻ തലത്തിലോ ഉള്ള വിശകലനമല്ല.",
        baselineTitle: "ത്രെഷോൾഡ് ബേസ്‌ലൈൻ പ്രവർത്തിപ്പിക്കുക",
        baselineBody:
          "മോഡൽ അനുകരിക്കാൻ പഠിച്ച പരമ്പരാഗത ഒപ്റ്റിക്കൽ-ഡെൻസിറ്റി ത്രെഷോൾഡ് നിയമത്തിലൂടെ അതേ ഫീൽഡ് കടത്തിവിടുന്നു; രണ്ട് ഫലങ്ങളും അടുത്തടുത്ത് കാണിക്കുന്നു.",
        quantifyTitle: "വ്യത്യാസം അളക്കുക",
        quantifyBody:
          "രണ്ട് രീതികളും വ്യത്യസ്തമായി തരംതിരിക്കുന്ന ടിഷ്യു പിക്സലുകളുടെ പങ്ക് ഒറ്റ സംഖ്യയായി നൽകുന്നു; കൺഫോർമൽ കാലിബ്രേഷൻ ലോഡ് ചെയ്തിട്ടുണ്ടെങ്കിൽ, ഒന്നിലധികം വിഭാഗങ്ങളുള്ള പ്രവചനഗണമുള്ളവയുടെ പങ്കും നൽകുന്നു.",
        handTitle: "പാത്തോളജിസ്റ്റിന് കൈമാറുക",
        handBody:
          "പേരു വ്യക്തമാക്കിയ ഒരു പരിശോധകൻ സ്കോർ തിരഞ്ഞെടുത്ത് സമർപ്പിക്കുന്നതുവരെ ഒന്നും രേഖപ്പെടുത്തുന്നില്ല. ഉപകരണത്തിന്റെ സ്വന്തം ഫലം ഒരിക്കലും ഒരു വിലയിരുത്തലായി കണക്കാക്കുന്നില്ല.",
      },
      data: {
        localTitle: "അപ്‌ലോഡുകൾ ഇവിടെത്തന്നെ നിൽക്കുന്നു",
        localBody:
          "അപ്‌ലോഡ് ചെയ്ത ഫീൽഡ് ബ്രൗസറിൽ വായിച്ച് ലോക്കൽ ബാക്കെൻഡിലേക്ക് അയയ്ക്കുന്നു. മൂന്നാമതൊരു കക്ഷിക്കും ഒന്നും അയയ്ക്കുന്നില്ല.",
        logTitle: "പരിശോധനകൾ ഇവിടെത്തന്നെ രേഖപ്പെടുത്തുന്നു",
        logBody:
          "സമർപ്പിച്ച വിലയിരുത്തലുകൾ സെർവർ പ്രവർത്തിക്കുന്ന കമ്പ്യൂട്ടറിലെ ഒരു JSONL ഫയലിൽ ചേർക്കുന്നു.",
        reportTitle: "റിപ്പോർട്ടുകൾ സെർവറിലാണ് തയ്യാറാക്കുന്നത്",
        reportBody:
          "സ്ക്രീനിൽ കാണിക്കുന്ന അതേ ചിത്രങ്ങളും അളവുകളും മുന്നറിയിപ്പുകളും തന്നെയാണ് PDF-ൽ ഉള്ളത് — അതിൽ കൂടുതലുമില്ല, കുറവുമില്ല.",
      },
      refs: {
        amilTitle:
          "Additive MIL: Intrinsically Interpretable Multiple Instance Learning from Pathology",
        amilMeta: "Javed തുടങ്ങിയവർ, CVPR 2022 · arXiv:2206.01794",
        pathaiTitle: "PathAI AIM-HER2 Breast Cancer",
        pathaiMeta: "താരതമ്യത്തിനായി, ഇതേ മേഖലയിലെ ഒരു വാണിജ്യ സംവിധാനം",
      },
    },

    toast: {
      dismiss: "അറിയിപ്പ് മാറ്റുക",
      demoTitle: "ഡെമോ ഡാറ്റയാണ് കാണിക്കുന്നത്",
      demoBody: "ഈ പേജിൽ നിന്ന് Python ബാക്കെൻഡിലേക്ക് എത്താനാകുന്നില്ല.",
      analysedTitle: "ഫീൽഡ് വിശകലനം ചെയ്തു",
      analysedBody: "വിലയിരുത്തൽ രേഖപ്പെടുത്തും മുൻപ് അളവുകൾ പരിശോധിക്കുക.",
      analysisFailed: "വിശകലനം പരാജയപ്പെട്ടു",
      selectTitle: "ഒരു വിലയിരുത്തൽ തിരഞ്ഞെടുക്കുക",
      selectBody: "ഒരു സ്കോർ തിരഞ്ഞെടുക്കുക, അല്ലെങ്കിൽ “വിലയിരുത്താനാകില്ല”.",
      recordedTitle: "വിലയിരുത്തൽ രേഖപ്പെടുത്തി",
      recordedDemo: "ഈ ബ്രൗസറിൽ മാത്രം സൂക്ഷിച്ചു — എഴുതാൻ ബാക്കെൻഡില്ല.",
      recordedLive: "{log} എന്നതിൽ എഴുതി",
      recordFailed: "അത് രേഖപ്പെടുത്താനായില്ല",
      reportTitle: "റിപ്പോർട്ട് ഡൗൺലോഡ് ചെയ്തു",
      reportBody: "കാണിച്ചതുപോലെ ചിത്രങ്ങളും അളവുകളും എല്ലാ മുന്നറിയിപ്പുകളും.",
      reportFailed: "റിപ്പോർട്ട് ലഭ്യമല്ല",
      chooseFirst: "ആദ്യം ഒരു ഉദാഹരണ പാച്ച് തിരഞ്ഞെടുക്കുക അല്ലെങ്കിൽ ഒരു ചിത്രം അപ്‌ലോഡ് ചെയ്യുക.",
    },

    demo: {
      role: "കൺസൾട്ടന്റ് പാത്തോളജിസ്റ്റ്",
      department: "പാത്തോളജി · ഗവ. മെഡിക്കൽ കോളേജ് കോട്ടയം",
      notes: {
        heterogeneous: "വൈവിധ്യമുള്ളത്; ISH പരിശോധന ആവശ്യപ്പെട്ടു.",
        strong: "എല്ലായിടത്തും ശക്തവും പൂർണവുമായ മെംബ്രെയ്ൻ സ്റ്റെയിനിങ്.",
        crush: "മുകൾവശത്തെ ക്രഷ് ആർട്ടിഫാക്ടിൽ മോഡൽ 1+ എന്ന് അധികമായി കണക്കാക്കുന്നു.",
        insufficient: "ഈ ഫീൽഡിൽ ഇൻവേസീവ് ട്യൂമർ പര്യാപ്തമല്ല.",
      },
    },

    caveats: {
      not_a_score:
        "ഈ ഉപകരണം HER2 സ്കോർ നിർണയിക്കുന്നില്ല. കണ്ടെത്തിയ ടിഷ്യുവിൽ എത്രമാത്രം ഓരോ സ്റ്റെയിൻ-തീവ്രതാ വിഭാഗത്തിൽ വരുന്നു എന്ന് അളക്കുകയും അത് എവിടെയാണെന്ന് കാണിക്കുകയും മാത്രമാണ് ഇത് ചെയ്യുന്നത്. ഒരു കേസിന് 0 / 1+ / 2+ / 3+ നൽകുന്നത് ഇപ്പോഴും പാത്തോളജിസ്റ്റിന്റെ തീരുമാനമാണ് — മുഴുവൻ സ്ലൈഡിലെയും മെംബ്രെയ്ൻ പൂർണതയും സ്റ്റെയിനിങ് രീതിയും നോക്കി എടുക്കുന്ന തീരുമാനം, ഒരൊറ്റ ഫീൽഡിലെ വിസ്തീർണ ശതമാനം നോക്കിയല്ല.",
      model_limitation:
        "ഈ മോഡലിന്റെ ഏറ്റവും ദുർബലമായ ഭാഗം 2+ വിഭാഗമാണ്. ഒപ്റ്റിക്കൽ-ഡെൻസിറ്റി ത്രെഷോൾഡുകളിൽ നിന്ന് ഉരുത്തിരിഞ്ഞ സ്യൂഡോ-ലേബലുകൾ ഉപയോഗിച്ചാണ് ഇത് പരിശീലിച്ചത്; ആ ത്രെഷോൾഡുകൾക്ക് ഏറ്റവും വിശ്വാസ്യത കുറവുള്ളത് കൃത്യമായും 2+ എന്നിടത്താണ്. ഏതൊരു 2+ വിസ്തീർണക്കണക്കും നോക്കാനുള്ള സൂചനയായി കാണുക, ഉദ്ധരിക്കാനുള്ള അളവായിട്ടല്ല.",
      targets:
        "പാത്തോളജിസ്റ്റുകളുടെ സ്കോറുകൾ ആവർത്തിക്കാനല്ല, പരമ്പരാഗത DAB ഒപ്റ്റിക്കൽ-ഡെൻസിറ്റി ത്രെഷോൾഡ് നിയമം അനുകരിക്കാനാണ് മോഡലിനെ പരിശീലിപ്പിച്ചത്. ഒരു പാത്തോളജിസ്റ്റിന്റെ ലേബൽ അത് ഒരിക്കലും കണ്ടിട്ടില്ല. ത്രെഷോൾഡ് ബേസ്‌ലൈനുമായി അത് വിയോജിക്കുന്നിടത്ത്, മോഡൽ സാമാന്യവൽക്കരിക്കുകയാണ് — അത് ശരിയാകാം, തെറ്റാകാം; അത് കാണാൻ കഴിയേണ്ടതിനാണ് രണ്ട് നിരകളും അടുത്തടുത്ത് കാണിക്കുന്നത്.",
      denominator:
        "താഴെയുള്ള ഓരോ ശതമാനവും കണ്ടെത്തിയ ടിഷ്യു വിസ്തീർണത്തിന്റെ പങ്കാണ്, ട്യൂമർ കോശങ്ങളുടെ പങ്കല്ല. സ്ട്രോമ, ലിംഫോസൈറ്റുകൾ, സാധാരണ ഡക്ടുകൾ, കൺട്രോൾ ടിഷ്യു എന്നിവയെല്ലാം ഛേദത്തിനുള്ളിലുണ്ട്. ക്ലിനിക്കൽ നിയമം എണ്ണുന്നത് പൂർണമായ മെംബ്രെയ്ൻ സ്റ്റെയിനിങ്ങുള്ള ഇൻവേസീവ് ട്യൂമർ കോശങ്ങളെയാണ് — അത് തീർത്തും വ്യത്യസ്തമായ ഒരു അളവാണ്.",
    },
  },
};
