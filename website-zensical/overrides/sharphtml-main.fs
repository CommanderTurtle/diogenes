module DiogenesDocs.Overrides.MainHtml

let file = """{% extends "base.html" %}

{% block extrahead %}
  {{ super() }}
  <meta property="og:type" content="website">
  <meta property="og:url" content="https://dio.shel.sh/">
  <meta property="og:title" content="diogenes">
  <meta property="og:description" content="bloated with materialism, nihilistic in theory.">
  <meta property="og:locale" content="en_US">
  <meta name="twitter:card" content="summary">
  <meta name="theme-color" content="#101005">
{% endblock %}

{% block announce %}{% endblock %}

{% block scripts %}
  {{ super() }}
  <script type="module" src="{{ 'assets/javascripts/home.js' | url }}"></script>
{% endblock %}
"""

let render() = file
