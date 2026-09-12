module DiogenesDocs.HomeMd

let file = """---
hide:
  - navigation
  - toc
---

<div class="dio-home">
  <p class="dio-home__name">diogenes</p>
  <p class="dio-home__tagline">bloated with materialism, nihilistic in theory.</p>
  <nav class="dio-home__links" aria-label="Start">
    <a href="getting-started/installation/">install</a>
    <a href="getting-started/quickstart/">quickstart</a>
    <a href="reference/feature-matrix/">features</a>
    <a href="https://github.com/CommanderTurtle/diogenes">git</a>
    <a class="dio-home__about" href="about/diogenes/">about</a>
  </nav>
</div>
"""

let render() = file
