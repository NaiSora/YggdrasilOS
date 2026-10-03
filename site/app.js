// Le site d'Yggdrasil. Les versions, leurs fichiers et leurs notes viennent des releases
// GitHub : rien à tenir à jour ici. Sans réseau ou sans JavaScript, les liens vers GitHub restent.
"use strict";

const PROJET = "NaiSora/YggdrasilOS";
const API = `https://api.github.com/repos/${PROJET}/releases?per_page=30`;
const RELEASES = `https://github.com/${PROJET}/releases`;

const nombre = new Intl.NumberFormat("fr-FR", { maximumFractionDigits: 1 });
const jour = new Intl.DateTimeFormat("fr-FR", { dateStyle: "long" });

function taille(octets) {
    if (octets >= 1e9) return `${nombre.format(octets / 1e9)} Go`;
    if (octets >= 1e6) return `${nombre.format(octets / 1e6)} Mo`;
    return `${nombre.format(Math.max(octets, 1) / 1e3)} ko`;
}

function element(nom, attributs = {}, ...enfants) {
    const e = document.createElement(nom);
    for (const [cle, valeur] of Object.entries(attributs)) {
        if (cle === "texte") e.textContent = valeur;
        else e.setAttribute(cle, valeur);
    }
    e.append(...enfants);
    return e;
}

// Une seule demande à GitHub par page, partagée
let demande = null;
function versions() {
    if (demande) return demande;
    demande = fetch(API, { headers: { Accept: "application/vnd.github.html+json" } })
        .then((r) => {
            if (!r.ok) throw new Error(`GitHub a répondu ${r.status}`);
            return r.json();
        })
        .then((liste) => liste.filter((v) => !v.draft && !v.prerelease));
    return demande;
}

// Les fichiers d'une version : ISO bureau (en morceaux), ISO serveur, sources, sommes
function classer(fichiers) {
    const c = { bureau: [], serveur: [], sources: [], sommes: null };
    for (const f of fichiers) {
        if (/^yggdrasil-[\d.]+-amd64\.iso(\.\d{3})?$/.test(f.name)) c.bureau.push(f);
        else if (/^yggdrasil-serveur-[\d.]+-amd64\.iso(\.\d{3})?$/.test(f.name)) c.serveur.push(f);
        else if (/sources\.tar(\.\d{3})?$/.test(f.name)) c.sources.push(f);
        else if (f.name === "SHA256SUMS") c.sommes = f;
    }
    for (const liste of [c.bureau, c.serveur, c.sources]) liste.sort((a, b) => a.name.localeCompare(b.name));
    return c;
}

function boutonCopier(texte) {
    const b = element("button", { type: "button", class: "copier", texte: "copier" });
    const afficher = (message) => {
        b.textContent = message;
        setTimeout(() => { b.textContent = "copier"; }, 2000);
    };
    b.addEventListener("click", () => {
        if (!navigator.clipboard) return afficher("copie impossible");
        navigator.clipboard.writeText(texte).then(() => afficher("copié ✓"), () => afficher("copie impossible"));
    });
    return b;
}

function ligneFichier(f) {
    const li = element("li", { class: "fichier" },
        element("span", { class: "nom", texte: f.name }),
        element("a", { class: "bouton petit", href: f.browser_download_url, texte: `Télécharger · ${taille(f.size)}` }));
    if (f.digest && f.digest.startsWith("sha256:")) {
        const somme = f.digest.slice(7);
        li.append(element("span", { class: "empreinte" },
            element("span", { texte: `SHA-256 ${somme}` }), boutonCopier(somme)));
    }
    return li;
}

function remplirTelechargements(v) {
    const c = classer(v.assets);
    const date = jour.format(new Date(v.published_at));
    const meta = document.querySelector("[data-meta-version]");
    if (meta) meta.textContent = `Version ${v.tag_name.replace(/^v/, "")} · publiée le ${date} · Debian 13 · KDE Plasma 6.3`;
    const chapeau = document.querySelector("[data-chapeau-telecharger]");
    if (chapeau) {
        // La dernière version ici ; les précédentes restent téléchargeables dans leurs releases
        chapeau.replaceChildren(`${v.name || v.tag_name}, publiée le ${date}. `,
            element("a", { href: "notes.html", texte: "Ce qui a changé" }), ". Les versions précédentes : ",
            element("a", { href: RELEASES, texte: "toutes les releases" }), ".");
    }
    const bouton = document.querySelector("[data-bouton-version]");
    if (bouton) bouton.textContent = `Télécharger Yggdrasil ${v.tag_name.replace(/^v/, "")}`;
    for (const edition of ["bureau", "serveur"]) {
        const liste = document.querySelector(`[data-fichiers="${edition}"]`);
        if (!liste || c[edition].length === 0) continue;
        liste.replaceChildren(...c[edition].map(ligneFichier));
        const total = c[edition].reduce((s, f) => s + f.size, 0);
        const morceaux = c[edition].length > 1 ? ` en ${c[edition].length} morceaux` : "";
        document.querySelector(`[data-taille="${edition}"]`).textContent = `${taille(total)}${morceaux}`;
    }
    // Les commandes pour recoller, avec les vrais noms de fichiers
    const parties = c.bureau.filter((f) => /\.\d{3}$/.test(f.name)).map((f) => f.name);
    if (parties.length > 1) {
        const iso = parties[0].replace(/\.\d{3}$/, "");
        document.querySelector('[data-recoller="windows"]').textContent =
            `cmd /c copy /b ${parties.join(" + ")} ${iso}\nGet-FileHash ${iso}`;
        document.querySelector('[data-recoller="linux"]').textContent =
            `cat ${parties.join(" ")} > ${iso}\nsha256sum -c SHA256SUMS --ignore-missing`;
    }
    if (c.sommes) document.querySelector("[data-lien-sommes]")?.setAttribute("href", c.sommes.browser_download_url);
    const sources = document.querySelector("[data-sources]");
    if (sources && c.sources.length) {
        sources.replaceChildren(`${c.sources.length} archives de sources, ${taille(c.sources.reduce((s, f) => s + f.size, 0))} : `,
            element("a", { href: v.html_url, texte: "dans la release" }));
    }
}

function remplirNotes(liste, conteneur) {
    if (liste.length === 0) {
        conteneur.replaceChildren(element("p", { class: "muet", texte: "Aucune version publiée pour l'instant." }));
        return;
    }
    conteneur.replaceChildren(...liste.map((v, i) => {
        const titre = element("header", {},
            element("h2", { id: v.tag_name, texte: v.name || v.tag_name }),
            element("time", { class: "muet", datetime: v.published_at, texte: jour.format(new Date(v.published_at)) }));
        if (i === 0) titre.append(element("span", { class: "badge", texte: "dernière version" }));
        const corps = element("div", { class: "corps-notes" });
        // Le texte des notes, déjà mis en forme et assaini par GitHub (body_html)
        corps.innerHTML = v.body_html || "";
        const c = classer(v.assets);
        const pied = element("p", { class: "muet" });
        const total = [...c.bureau, ...c.serveur].reduce((s, f) => s + f.size, 0);
        pied.append(total ? `Images : ${taille(total)}. ` : "",
            element("a", { href: v.html_url, texte: "Voir la release sur GitHub" }));
        return element("article", { class: "carte version-notes" }, titre, corps, pied);
    }));
    if (location.hash) document.getElementById(location.hash.slice(1))?.scrollIntoView();
}

function galerie() {
    const visionneuse = document.querySelector("dialog.visionneuse");
    if (!visionneuse) return;
    const image = visionneuse.querySelector("img");
    const legende = visionneuse.querySelector("p");
    document.querySelectorAll(".galerie button").forEach((b) => {
        b.addEventListener("click", () => {
            const vignette = b.querySelector("img");
            // La vignette est souvent la petite variante (srcset) : la visionneuse prend la grande
            image.src = vignette.dataset.grand || vignette.currentSrc || vignette.src;
            image.alt = vignette.alt;
            legende.textContent = b.closest("figure").querySelector("figcaption").textContent;
            visionneuse.showModal();
        });
    });
    visionneuse.querySelector(".fermer").addEventListener("click", () => visionneuse.close());
    visionneuse.addEventListener("click", (e) => { if (e.target === visionneuse) visionneuse.close(); });
}

function onglets() {
    const boutons = [...document.querySelectorAll('.onglets [role="tab"]')];
    const choisir = (b) => {
        for (const autre of boutons) {
            const choisi = autre === b;
            autre.setAttribute("aria-selected", String(choisi));
            autre.tabIndex = choisi ? 0 : -1;
            document.getElementById(autre.getAttribute("aria-controls")).hidden = !choisi;
        }
    };
    boutons.forEach((b, i) => {
        b.addEventListener("click", () => choisir(b));
        b.addEventListener("keydown", (e) => {
            const pas = { ArrowRight: 1, ArrowLeft: -1 }[e.key];
            if (!pas) return;
            const suivant = boutons[(i + pas + boutons.length) % boutons.length];
            choisir(suivant);
            suivant.focus();
        });
    });
    // Le système du visiteur, d'abord
    if (!/Windows/i.test(navigator.userAgent) && boutons[1]) choisir(boutons[1]);
}

document.addEventListener("DOMContentLoaded", () => {
    galerie();
    onglets();
    const notes = document.querySelector("[data-notes]");
    const aTelecharger = document.querySelector("[data-fichiers]");
    if (!notes && !aTelecharger) return;
    versions().then((liste) => {
        if (aTelecharger && liste.length) remplirTelechargements(liste[0]);
        if (notes) remplirNotes(liste, notes);
    }).catch((erreur) => {
        if (notes) {
            notes.replaceChildren(element("p", { class: "muet" },
                `Les notes n'ont pas pu être chargées depuis GitHub (${erreur.message}). Elles sont aussi `,
                element("a", { href: RELEASES, texte: "sur la page des releases" }), "."));
        }
    });
});
