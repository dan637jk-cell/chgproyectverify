(function(){
// Simple i18n helper with global access
window.i18n = {
  currentLang: 'en',
  data: {},
  listeners: [],
  t(key, fallback) {
    const val = (this.data && key) ? this.data[key] : undefined;
    return (typeof val === 'string') ? val : (fallback !== undefined ? fallback : key || '');
  },
  onChange(cb){ if (typeof cb === 'function') this.listeners.push(cb); },
  _emit(){ this.listeners.forEach(cb => { try{ cb(this.currentLang, this.data); }catch(e){} }); }
};

async function fetchLanguageData(lang) {
  const response = await fetch(`/static/lang/${lang}.json`, { cache: 'no-store' });
  return response.json();
}

function updateTextNodes(langData) {
  // Update all elements that declare a translation key
  const elements = document.querySelectorAll('[data-lang-key]');
  elements.forEach(el => {
    const key = el.getAttribute('data-lang-key');
    if (!key) return;
    const txt = langData[key];
    if (typeof txt !== 'string') return;

    const attr = el.getAttribute('data-i18n-attr');
    if (attr) {
      el.setAttribute(attr, txt);
      return;
    }

    // Special cases by tag
    const tag = (el.tagName || '').toUpperCase();
    if (tag === 'INPUT' || tag === 'TEXTAREA') {
      // Inputs generally use placeholder via separate selector below
      // but if someone marked it with data-lang-key we can set value placeholder
      if (el.hasAttribute('placeholder')) el.setAttribute('placeholder', txt);
      else el.value = txt;
      return;
    }
    if (tag === 'IMG') {
      el.setAttribute('alt', txt);
      return;
    }

    // Default to textContent to avoid injecting HTML
    el.textContent = txt;
  });

  // Update placeholders only on elements that declare data-lang-key as well
  const placeholders = document.querySelectorAll('[placeholder][data-lang-key]');
  placeholders.forEach(el => {
    const key = el.getAttribute('data-lang-key');
    if (!key) return;
    const txt = langData[key];
    if (typeof txt === 'string') el.setAttribute('placeholder', txt);
  });

  // Update <title data-lang-key="...">
  const titleEl = document.querySelector('title[data-lang-key]');
  if (titleEl) {
    const key = titleEl.getAttribute('data-lang-key');
    if (key && langData[key]) titleEl.textContent = langData[key];
  }
}

async function changeLanguage(lang) {
  try {
    localStorage.setItem('language', lang);
    document.documentElement.setAttribute('lang', lang);
    const langData = await fetchLanguageData(lang);
    window.i18n.currentLang = lang;
    window.i18n.data = langData || {};

    updateTextNodes(window.i18n.data);

    // Sync language selectors if present
    const ids = ['lang-switcher', 'lang-switcher-mobile'];
    ids.forEach(id => {
      const sel = document.getElementById(id);
      if (sel) sel.value = lang;
    });

    window.i18n._emit();
  } catch(e) {
    console.error('Failed to change language', e);
  }
}

function setupLanguageSwitcher(){
  const desktop = document.getElementById('lang-switcher');
  const mobile = document.getElementById('lang-switcher-mobile');

  function onChange(ev){
    const selected = ev.target.value;
    changeLanguage(selected);
    // Mirror value across both selectors
    if (desktop && ev.target !== desktop) desktop.value = selected;
    if (mobile && ev.target !== mobile) mobile.value = selected;
  }

  if (desktop) desktop.addEventListener('change', onChange);
  if (mobile) mobile.addEventListener('change', onChange);
}

document.addEventListener('DOMContentLoaded', () => {
  setupLanguageSwitcher();
  const saved = localStorage.getItem('language') || 'en';
  changeLanguage(saved);
});

// Expose function globally for other scripts
window.changeLanguage = changeLanguage;
})();
