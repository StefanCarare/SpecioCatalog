"""Bilingual strings (RO/EN) for Specio Catalog.

Each entry maps a key to a ``(ro, en)`` tuple. ``t(key)`` returns the text
for the language selected with :func:`set_language`.
"""
from __future__ import annotations

STRINGS: dict[str, tuple[str, str]] = {
    "app_title": ("Specio Catalog — consultare catalog", "Specio Catalog — catalog browser"),
    "language_lbl": ("Limbă", "Language"),
    "search_lbl": ("Căutare:", "Search:"),
    "search_btn": ("Caută", "Search"),
        "criteria_lbl": ("Criteriu:", "Criteria:"),
    "category_lbl": ("Grup:", "Group:"),
    "all_cat": ("Toate", "All"),
    "results_lbl": ("Specii găsite", "Species found"),
    "view_lbl": ("Vedere:", "View:"),
    "view_tree": ("Arbore", "Tree"),
    "view_list": ("Listă", "List"),
    "tree_other": ("Alte grupuri", "Other groups"),
    "tree_kingdom": ("Regnul", "Kingdom"),
    "results_count": ("{n} specii | {m} poze", "{n} species | {m} photos"),
    "detail_none": ("Selectează o specie din listă.", "Select a species from the list."),
    "sci_lbl": ("Nume științific:", "Scientific name:"),
    "common_lbl": ("Denumiri populare:", "Common names:"),
    "date_lbl": ("Data pozei:", "Photo date:"),
    "loc_lbl": ("Locație:", "Location:"),
    "file_lbl": ("Fișier:", "File:"),
    "photo_nav": ("Poză {i} / {n}", "Photo {i} / {n}"),
    "prev_btn": ("◀ Anterioara", "◀ Previous"),
    "next_btn": ("Următoarea ▶", "Next ▶"),
    "no_photo": ("(fără fotografie pe disc)", "(no photo on disk)"),
    "photo_missing": ("Poză lipsă pe disc", "Photo missing on disk"),
    "profile_lbl": ("Descriere profil:", "Profile description:"),
    "no_profile": ("(specia nu are profil generat)", "(species has no generated profile)"),
    "structured_lbl": ("Date structurate", "Structured data"),
    "open_folder_btn": ("Deschide folderul speciei", "Open species folder"),
    "folder_missing": ("Folderul speciei nu a fost găsit pe disc.", "Species folder was not found on disk."),
    "btn_open_col": ("🌐 CoL", "🌐 CoL"),
    "btn_open_wikipedia": ("🌐 WIKIPEDIA", "🌐 WIKIPEDIA"),
    "web_title": ("Verificare web", "Web lookup"),
    "web_no_species": ("Nu este selectată nicio specie.", "No species is selected."),
    "web_copied_clipboard": (
        "Numele '{name}' a fost copiat în clipboard — pe pagina CoL apasă Ctrl+V.",
        "The name '{name}' was copied to the clipboard — on the CoL page just press Ctrl+V.",
    ),
    "status_web_open": ("Se deschide Wikipedia: {name}", "Opening Wikipedia: {name}"),
    "db_error_title": ("Catalog indisponibil", "Catalog unavailable"),
    "invalid_root_msg": (
        "In folderul ales nu există output\\catalog.db.\nAlege folderul proiectului SpecioIdentify.",
        "The chosen folder has no output\\catalog.db.\nChoose the SpecioIdentify project folder.",
    ),
    "choose_root_title": ("Alege proiectul SpecioIdentify", "Choose the SpecioIdentify project"),
    "choose_root_msg": (
        "Alege folderul proiectului SpecioIdentify\n(cel care conține output\\catalog.db).",
        "Choose the SpecioIdentify project folder\n(the one containing output\\catalog.db).",
    ),
    "status_open_fail": ("Nu pot deschide catalogul: {err}", "Cannot open the catalog: {err}"),
    "search_suggestion": ("Sugestii căutare:", "Search suggestions:"),
    "no_suggestions": ("Fără sugestii", "No suggestions"),
    "crit_any_name": ("Oricare denumire", "Any name"),
    "crit_scientific": ("Nume științific", "Scientific name"),
    "crit_popular_ro": ("Denumire populară RO", "Popular name RO"),
    "crit_popular_en": ("Denumire populară EN", "Popular name EN"),
    "crit_profile_text": ("Text profil", "Profile text"),
    "no_results": ("Niciun rezultat.", "No results."),
    "open_failed": ("Nu pot deschide: {err}", "Cannot open: {err}"),
    "change_catalog_btn": ("Schimbă catalogul", "Change catalog"),
    "status_ready": ("Catalog: {root}", "Catalog: {root}"),
    "status_not_open": ("Catalogul nu este deschis.", "No catalog is open."),
    "col_photos": ("Poze", "Photos"),
    # Phase A — determinator (trait filter over normalized profile fields).
    "det_btn": ("🔍 Determinator", "🔍 Determiner"),
    "det_title": ("Criterii de determinare (câmp + valoare):", "Determination criteria (field + value):"),
    "det_add": ("+ Criteriu", "+ Criterion"),
    "det_summary": (
        "{n} specii | {m} poze — {e} exacte, {i} date incomplete",
        "{n} species | {m} photos — {e} exact, {i} incomplete",
    ),
    "det_none": ("Nicio specie nu corespunde criteriilor.", "No species matches the criteria."),
    # Phase B — guided dichotomous key (Determinator mode).
    "det_mode_free": ("Filtru liber", "Free filter"),
    "det_mode_key": ("Cheie ghidată", "Guided key"),
    "det_key_progress": (
        "Pasul {step} · {n} din {total} rămase ({e} exacte, {i} ?)",
        "Step {step} · {n} of {total} left ({e} exact, {i} ?)",
    ),
    "det_key_one": ("O singură specie rămasă!", "A single species remains!"),
    "det_key_none": (
        "Nicio specie nu corespunde răspunsurilor date.",
        "No species matches the given answers.",
    ),
    "det_key_exhausted": (
        "Cheia nu mai are întrebări discriminante — {n} specii rămân.",
        "The key has no more discriminating questions — {n} species remain.",
    ),
    "det_key_unknown": (
        "{u} specii nu au această trăsătură și rămân marcate cu „?”",
        "{u} species lack this trait and stay marked with “?”",
    ),
    "det_key_path": ("Alegeri: {path}", "Choices: {path}"),
    "det_key_skipped": ("sărit", "skipped"),
    "det_key_back": ("◀ Înapoi", "◀ Back"),
    "det_key_skip": ("Nu știu / sar peste", "Don't know / skip"),
    "det_key_restart": ("Reîncepe", "Restart"),
    # ---- describe & find (phase 3) ----
    # The two AI boxes are distinguished by what they return, not by how they
    # look: this one only finds species, the question box also answers.
    "ai_title": ("🔎 Găsește după descriere", "🔎 Find by description"),
    "ai_hint": (
        "Descrie ce ai văzut, în cuvintele tale. Doar rezultate, fără răspuns:",
        "Describe what you saw, in your own words. Results only, no answer:",
    ),
    "ai_model_lbl": ("Model:", "Model:"),
    "ai_model_refresh": ("⟳", "⟳"),
    "ai_placeholder": (
        "ex: floare roșie, 5 petale, la câmpie",
        "e.g. red flower, 5 petals, in a field",
    ),
    "ai_btn": ("Caută", "Search"),
    "ai_refine_hint": (
        "Adaugă un detaliu sau schimbă ceva:",
        "Add a detail or change something:",
    ),
    "ai_busy": ("Se găsește…", "Searching…"),
    "ai_elapsed": ("{sec}s", "{sec}s"),
    "ai_cancel": ("⏹ Oprește", "⏹ Stop"),
    "ai_reset": ("✕ Resetează", "✕ Reset"),
    "ai_used": ("Filtre folosite:", "Filters used:"),
    "ai_words": ("căutare:", "searched:"),
    "ai_why": ("Se potrivește:", "Matches:"),
    "ai_unknown": ("necunoscut:", "unknown:"),
    "ai_snapped": (
        "corectat: {was} → {now}",
        "corrected: {was} → {now}",
    ),
    "ai_dropped": (
        "ignorat (nu există în catalog): {items}",
        "ignored (not in the catalogue): {items}",
    ),
    "ai_unknown_field": (
        "câmp necunoscut: {fields}",
        "unknown field: {fields}",
    ),
    "ai_no_result": (
        "Niciun rezultat. Încearcă o descriere mai simplă.",
        "No result. Try a simpler description.",
    ),
    "ai_relaxed": (
        "Filtrul «{filters}» nu a lăsat niciun rezultat — "
        "am căutat doar după cuvintele tale.",
        "Filter “{filters}” left no result — searched your words only.",
    ),
    # ---- question box (chat with the catalogue) ----
    "chat_title": ("💬 Întreabă speciile", "💬 Ask the species"),
    "chat_hint": (
        "Întreabă despre speciile afișate sau descrie altceva. Răspunsurile se "
        "bazează doar pe profilele lor, nu pe cunoștințe generale.",
        "Ask about the species on screen, or describe something else. Answers "
        "come only from their profiles, not from general knowledge.",
    ),
    "brand_name": ("Specio Catalog", "Specio Catalog"),
    "brand_sub": (
        "consultare catalog Specio Identify",
        "browsing the Specio Identify catalogue",
    ),
    "help_button": ("❓ Ghid", "❓ Guide"),
    "help_title": ("Ghid — Specio Catalog", "Guide — Specio Catalog"),
    "help_size": ("Mărimea textului:", "Text size:"),
    # Each entry is a heading, then its paragraphs. A paragraph is one long
    # line on purpose: the Text widget wraps it to whatever width the window
    # has, which is what makes the guide reflow. Pre-wrapping the strings here
    # would freeze the measure at whatever column the source file happened to
    # use and the window width would stop mattering.
    "help_body": (
        {
            "Ce este Specio Catalog": (
                "Citește catalogul unui proiect SpecioIdentify. Nu modifică nimic: baza de date se deschide doar pentru citire.",
            ),
            "Căutare": (
                "Criteriu — după ce cauți: nume științific, nume românesc sau orice text din profil.",
                "Grup — planta, pasăre, mamifer, insectă, reptilă, amfibian.",
                "Rezultatele apar dedesubt; bara de jos arată câte sunt.",
            ),
            "Vedere: Arbore sau Listă": (
                "Arborele grupează speciile după linie taxonomică, Lista le arată în ordinea potrivirii, după rang. Trecerea dintr-una în cealaltă păstrează specia deschisă.",
            ),
            "Determinator (Filtrare liberă)": (
                "Adaugă rânduri de criterii: o caracteristică și o valoare. O specie care nu se potrivește e exclusă; una care nu are caracteristica marcată rămâne, dar ca „incompletă”.",
                "Pentru luni, „martie” prinde toate intervalele care conțin martie, nu doar pe cele scrise exact așa.",
            ),
            "Determinator (Cheie ghidată)": (
                "Pentru o identificare pas cu pas: fiecare întrebare are da sau nu, iar ramurile se restrâng până la o specie.",
            ),
            "🔎 Găsește după descriere": (
                "Scrie ce ai văzut, în cuvintele tale. Modelul pune filtrele și restrânge lista — criteriile apar în Determinator, unde le poți corecta. Doar rezultate, fără răspuns: rapid.",
            ),
            "💬 Întreabă speciile": (
                "Întreabă despre speciile afișate sau descrie altceva. Se pun filtre, apoi se răspunde folosind profilele care au rămas. Răspunsurile se bazează doar pe profilele catalogului, nu pe cunoștințe generale, iar termenii tehnici primesc o paranteză.",
                "↺ Subiect nou — discuție nouă; întrebarea următoare nu mai ține seama de cea anterioară.",
                "❓ De ce? — răspunde despre specia selectată, fără să schimbe lista.",
                "📖 Citește — discuția într-o fereastră îngustă, la lățime confortabilă. ↺ Citește tot arată tot istoricul.",
                "Model — modelul Ollama folosit de ambele casete.",
            ),
            "Butoanele de sub poze": (
                "Deschide folderul speciei, caută în Catalogue of Life și în Wikipedia. Dacă nu le vezi, derulează zona cu poze.",
            ),
            "Tastatură și mouse": (
                "Ctrl + roata — mărește sau micșorează textul, în fereastra principală și în cea de citit.",
                "Barele dintre panouri se trag; separatorul de jos mărește discuția.",
                "Escape — închide fereastra de ghid.",
            ),
        },
        {
            "What Specio Catalog is": (
                "Reads the catalogue of a SpecioIdentify project. It changes nothing: the database is opened read-only.",
            ),
            "Searching": (
                "Criterion — what to look for: scientific name, common name, or any text in the profile.",
                "Group — plant, bird, mammal, insect, reptile, amphibian.",
                "Results appear below; the status bar counts them.",
            ),
            "View: Tree or List": (
                "The tree groups species by lineage; the list shows them in match order, by rank. Switching keeps the open species.",
            ),
            "Determinator (free filtering)": (
                "Add criterion rows: a character and a value. A species that does not match is excluded; one that simply has no such character stays, marked as incomplete.",
                "For months, \"March\" catches every span containing March, not only the one spelled exactly that way.",
            ),
            "Determinator (guided key)": (
                "Step-by-step identification: every question is yes or no, and the branches narrow down to a single species.",
            ),
            "🔎 Find by description": (
                "Write what you saw, in your own words. The model sets the filters and narrows the list — the criteria show up in the Determinator, where you can correct them. Results only, no answer: quick.",
            ),
            "💬 Ask the species": (
                "Ask about the species on screen, or describe something else. Filters are applied first, then the answer is built from the profiles that survived them. Answers come only from the catalogue's own profiles, never from general knowledge, and technical terms get a short explanation.",
                "↺ New topic — start a fresh subject; the next question ignores the previous one.",
                "❓ Why? — answers about the selected species, list untouched.",
                "📖 Read — opens the conversation in a narrower, comfortable window. ↺ Read all shows the full history.",
                "Model — the Ollama model both boxes use.",
            ),
            "Buttons under the photo": (
                "Open the species folder, look it up in Catalogue of Life and in Wikipedia. If they are not visible, scroll the photo area.",
            ),
            "Keyboard and mouse": (
                "Ctrl + wheel — grows or shrinks the text, in the main window and in the reading window.",
                "The dividers between panes are draggable; the one at the bottom makes the conversation taller.",
                "Escape — closes the guide window.",
            ),
        },
    ),
    "chat_read_all": ("↺ Citește tot", "↺ Read all"),
    "chat_read_scope": ("Subiectul curent", "Current subject"),
    "chat_read_scope_all": (
        "Tot istoricul, cu tot cu subiectele vechi",
        "Full history, finished subjects included",
    ),
    "chat_read_title": (
        "Discuție — fereastră de citit", "Conversation — reading window",
    ),
    "chat_new": ("↺ Subiect nou", "↺ New topic"),
    "chat_new_topic": (
        "— subiect nou, întrebările anterioare nu mai contează —",
        "— new topic, earlier questions no longer count —",
    ),
    "chat_send": ("Întreabă", "Ask"),
    "chat_why": ("❓ De ce?", "❓ Why?"),
    "chat_you": ("Tu", "You"),
    "chat_bot": ("Speciile răspund:", "The species say:"),
    "chat_thinking": ("Se citesc profilele…", "Reading the profiles…"),
    "chat_no_species": (
        "Nu e nicio specie afișată. Caută ceva mai întâi.",
        "No species on screen. Search for something first.",
    ),
    "chat_why_q": ("De ce se potrivește {name}?", "Why does {name} match?"),
    "chat_empty": (
        "Profilele nu spun nimic despre asta.",
        "The profiles say nothing about this.",
    ),
    "chat_cancelled": ("(oprit)", "(stopped)"),
    "chat_filtering": (
        "Gândesc la filtre…", "Thinking about filters…",
    ),
    "chat_found": (
        "Filtrele au lăsat {n} specii.", "The filters left {n} species.",
    ),
    "chat_nothing": (
        "Filtrele nu au lăsat nicio specie. Încearcă altă descriere "
        "sau verifică criteriile de sus.",
        "The filters left no species. Try another description "
        "or check the criteria above.",
    ),
    "chat_reason": (
        "{text}   ← apeși aici ca să le vezi și să le schimbi",
        "{text}   ← press here to see and change them",
    ),
    "chat_filters_opened": (
        "Filtrele întrebării, editabile sus.", "This question's filters, editable above.",
    ),
    "chat_reason_fields": (
        "criterii: {names}", "criteria: {names}",
    ),
    "chat_reason_words": (
        "căutare în profiluri: {names}", "searched profiles for: {names}",
    ),
    "chat_reason_none": (
        "fără criterii — întrebarea e despre ce e deja pe ecran",
        "no criteria — the question is about what is already on screen",
    ),
    "ai_error_title": ("Căutare AI", "AI search"),
    "ai_error_ollama": (
        "Nu pot contacta Ollama. Serverul rulează?",
        "Cannot reach Ollama. Is the server running?",
    ),
    "ai_error_model": (
        "Modelul „{model}” nu este instalat. Verifică describe_model în config/settings.txt.",
        "Model “{model}” is not installed. Check describe_model in config/settings.txt.",
    ),
    "ai_offline": (
        "Asistentul AI este oprit (describe_model gol).",
        "The AI assistant is off (empty describe_model).",
    ),
}

_lang = "ro"
_RO, _EN = 0, 1


def set_language(lang: str) -> None:
    global _lang
    _lang = "en" if str(lang).lower().startswith("en") else "ro"


def current_language() -> str:
    return _lang


def t(key: str, **fmt) -> str:
    ro, en = STRINGS.get(key, (key, key))
    text = (ro if _lang == "ro" else en) or ro or key
    if fmt:
        try:
            text = text.format(**fmt)
        except (KeyError, IndexError, ValueError):
            pass
    return text
