module DiogenesDocs.Assets.ExtraCss

let file = """/* Diogenes documentation */
:root {
  --dio-accent: #c56a32;
  --dio-bg: #101005;
  --dio-panel: rgba(8, 8, 8, 0.62);
  --dio-panel-soft: rgba(8, 8, 8, 0.58);
  --dio-line: rgba(255, 255, 255, 0.12);
  --md-primary-fg-color: #171717;
  --md-primary-fg-color--light: #242424;
  --md-primary-fg-color--dark: #080808;
  --md-accent-fg-color: #cf7841;
  --md-accent-bg-color: #1c120d;
}

[data-md-color-scheme="default"],
[data-md-color-scheme="slate"] {
  --md-default-bg-color: #101005;
  --md-default-fg-color: #ece8e1;
  --md-default-fg-color--light: #b8b3ac;
  --md-default-fg-color--lighter: #8a867f;
  --md-default-fg-color--lightest: #55524d;
  --md-code-bg-color: rgba(0, 0, 0, 0.72);
  --md-code-fg-color: #e7e2da;
  --md-typeset-a-color: #d88650;
}

html { scroll-behavior: auto; }

body {
  min-height: 100vh;
  background: var(--dio-bg);
}

canvas.dio-flame-canvas {
  position: fixed;
  inset: 0;
  z-index: 0;
  display: block;
  width: 100%;
  height: 100%;
  cursor: default;
  opacity: 1;
  pointer-events: none;
  touch-action: auto;
}

body.dio-page-home canvas.dio-flame-canvas {
  cursor: grab;
  pointer-events: auto;
  touch-action: none;
}

body.dio-page-home {
  -webkit-user-select: none;
  user-select: none;
}

body.dio-page-home input,
body.dio-page-home textarea,
body.dio-page-home [contenteditable="true"] {
  -webkit-user-select: text;
  user-select: text;
}

body.dio-page-home .md-main {
  cursor: grab;
}

body.dio-page-home .md-main a { cursor: pointer; }

body.dio-page-home.dio-camera-dragging canvas.dio-flame-canvas,
body.dio-page-home.dio-camera-dragging .md-main { cursor: grabbing; }

.md-header,
.md-container,
.md-footer,
.md-dialog,
.md-progress {
  position: relative;
  z-index: 1;
}

.md-header {
  background: rgba(7, 7, 7, 0.92);
  border-bottom: 1px solid var(--dio-line);
  box-shadow: none;
}

.md-header__button.md-logo img,
.md-header__button.md-logo svg {
  width: auto;
  height: 1.65rem;
}

.md-container { z-index: auto; background: transparent; }

.md-main__inner { margin-top: 1rem; }

.md-sidebar__scrollwrap {
  background: var(--dio-panel-soft);
  border: 1px solid rgba(255, 255, 255, 0.07);
  border-radius: 0.45rem;
}

.md-content__inner {
  min-height: calc(100vh - 8rem);
  margin-bottom: 1.5rem;
  padding: 1.5rem 1.7rem 2.5rem;
  background: linear-gradient(
    90deg,
    rgba(7, 7, 7, 0.74),
    var(--dio-panel) 28%,
    rgba(7, 7, 7, 0.46) 50%,
    var(--dio-panel) 72%,
    rgba(7, 7, 7, 0.74)
  );
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 0.45rem;
}

.md-typeset {
  font-size: 0.78rem;
  line-height: 1.62;
  text-shadow: 0 1px 1px rgba(0, 0, 0, 0.72);
}

.md-typeset h1,
.md-typeset h2,
.md-typeset h3,
.md-typeset h4 {
  color: #f1eee8;
  font-weight: 520;
  letter-spacing: -0.015em;
}

.md-typeset h1 { font-size: 1.9rem; }
.md-typeset h2 { font-size: 1.32rem; }
.md-typeset h3 { font-size: 1.03rem; }

.md-typeset a:not(.md-button) {
  text-decoration-color: color-mix(in srgb, var(--md-typeset-a-color) 48%, transparent);
  text-underline-offset: 0.14em;
}

.md-typeset code { border-radius: 0.2rem; }

.md-typeset pre > code {
  border-left: 0.1rem solid rgba(207, 120, 65, 0.58);
}

.md-typeset table:not([class]),
.md-typeset .tabbed-set,
.md-typeset .admonition,
.md-typeset details {
  border-color: var(--dio-line);
  border-radius: 0.3rem;
  background: rgba(0, 0, 0, 0.34);
  box-shadow: none;
}

.md-typeset .tabbed-content { padding: 0 0.8rem 0.3rem; }

.md-nav__item--section > .md-nav__link { font-weight: 620; }

.md-footer,
.md-footer-meta { background: rgba(7, 7, 7, 0.9); }

.dio-home {
  display: grid;
  min-height: calc(100vh - 5.3rem);
  place-content: center;
  place-items: center;
  text-align: center;
  text-transform: lowercase;
}

.dio-home__name {
  margin: 0;
  color: #f2efe9;
  font-size: clamp(0.86rem, 1.2vw, 1rem);
  font-weight: 430;
  letter-spacing: 0.19em;
}

.dio-home__tagline {
  margin: 0.65rem 0 0;
  color: #aaa59d;
  font-size: clamp(0.64rem, 0.9vw, 0.74rem);
  letter-spacing: 0.075em;
}

.dio-home__links {
  position: relative;
  display: flex;
  gap: 1rem;
  margin-top: 1.15rem;
  font-size: 0.62rem;
  letter-spacing: 0.08em;
}

.dio-home__links a { color: #d7d2ca; }

.dio-home__about {
  position: absolute;
  top: 0;
  left: calc(100% + 1rem);
  width: max-content;
  color: #d88650 !important;
  font-size: inherit;
  letter-spacing: inherit;
  line-height: inherit;
  white-space: nowrap;
}

body.dio-page-home .md-main__inner { margin-top: 0; }

body.dio-page-home .md-content__inner {
  min-height: calc(100vh - 3rem);
  margin: 0;
  padding: 0;
  background: transparent;
  border: 0;
}

body.dio-page-home .md-content__inner > h1:first-child {
  display: none;
}

body.dio-page-home .md-content__button,
body.dio-page-home .md-footer { display: none; }

.dio-about-hero {
  width: calc(100% + 3.4rem);
  margin: -1.5rem -1.7rem 2rem;
  line-height: 0;
  text-align: center;
}

.dio-about-hero img {
  display: block;
  width: 100%;
  height: auto;
  margin: 0 auto;
  -webkit-mask-image: radial-gradient(ellipse 96% 92% at center, #000 67%, transparent 100%);
  mask-image: radial-gradient(ellipse 96% 92% at center, #000 67%, transparent 100%);
  filter: drop-shadow(0 0.9rem 1.8rem rgba(0, 0, 0, 0.5));
}

.dio-section-intro {
  margin: 0 0 1.2rem;
  padding: 0.75rem 0.9rem;
  border-left: 0.12rem solid var(--dio-accent);
  background: rgba(0, 0, 0, 0.28);
}

.dio-source-path {
  display: block;
  margin: 0.8rem 0 1rem;
  padding: 0.55rem 0.7rem;
  border: 1px solid var(--dio-line);
  background: rgba(0, 0, 0, 0.42);
  color: #c9c4bc;
  font-family: var(--md-code-font-family);
  font-size: 0.68rem;
}

.dio-mermaid {
  margin: 1.2rem auto;
  padding: 0.8rem;
  overflow-x: auto;
  background: rgba(0, 0, 0, 0.46);
  border: 1px solid var(--dio-line);
  border-radius: 0.3rem;
}

.dio-mermaid svg {
  display: block;
  max-width: 100%;
  height: auto;
  margin: auto;
}

.dio-render-error {
  color: #f18b83;
  font-family: var(--md-code-font-family);
  font-size: 0.68rem;
}

@media screen and (max-width: 76.2344em) {
  .md-sidebar__scrollwrap { background: rgba(7, 7, 7, 0.82); }
}

@media screen and (max-width: 44.9844em) {
  .md-content__inner {
    padding: 1rem 1rem 2rem;
    border-right: 0;
    border-left: 0;
    border-radius: 0;
  }
  .dio-home__links { gap: 0.75rem; }
  .dio-home__about { left: calc(100% + 0.7rem); }
  .dio-about-hero {
    width: calc(100% + 2rem);
    margin: -1rem -1rem 1.5rem;
  }
}
"""

let render() = file
