// Paste into the browser's JavaScript tool on a Zalando page (any country domain).
// Defines window.zsearch, window.zproduct and window.zverifyAll. Results are kept in
// localStorage under "lookbook-z:", so a long background run survives tool timeouts.

window.zsearch = async (path, n = 24) => {
  const r = await fetch(path, { credentials: 'include' });
  if (r.status !== 200) throw new Error('HTTP ' + r.status + ' for ' + path);
  const d = new DOMParser().parseFromString(await r.text(), 'text/html');
  const out = [];
  d.querySelectorAll('article').forEach((a) => {
    const l = a.querySelector('a[href*=".html"]');
    if (!l) return;
    const img = a.querySelector('img');
    out.push({
      slug: new URL(l.getAttribute('href'), location.origin).pathname.slice(1),
      text: (a.textContent || '').replace(/\s+/g, ' ').replace(/heart_outlined|Premium delivery/g, '').trim().slice(0, 170),
      img: img ? img.getAttribute('src') : '',
    });
  });
  return out.slice(0, n);
};

// Product pages render their data client-side, so read them in a hidden same-origin iframe.
window.zproduct = (slug) => new Promise((res) => {
  const f = document.createElement('iframe');
  f.style.cssText = 'position:fixed;left:-3000px;width:1200px;height:900px';
  const done = (v) => { f.remove(); res(v); };
  const to = setTimeout(() => done({ slug, err: 'timeout' }), 25000);
  f.onload = () => setTimeout(() => {
    clearTimeout(to);
    try {
      const d = f.contentDocument;
      let pg = null;
      d.querySelectorAll('script[type="application/ld+json"]').forEach((s) => {
        try {
          const j = JSON.parse(s.textContent);
          (Array.isArray(j) ? j : [j]).forEach((x) => { if (x && x.hasVariant) pg = x; });
        } catch (e) { /* not product data */ }
      });
      const variants = pg ? pg.hasVariant.map((v) => {
        const o = Array.isArray(v.offers) ? v.offers[0] : v.offers;
        return { size: v.size || v.name || '', inStock: /InStock/.test((o && o.availability) || ''), price: o && o.price };
      }) : [];
      const details = [];
      d.querySelectorAll('dt').forEach((dt) => {
        const dd = dt.nextElementSibling;
        if (dd) details.push(dt.innerText.trim().replace(/:$/, '') + ': ' + dd.innerText.trim());
      });
      const imgs = pg ? (Array.isArray(pg.image) ? pg.image : [pg.image]).filter(Boolean).slice(0, 4) : [];
      done({
        slug, brand: pg && pg.brand && pg.brand.name, name: pg && pg.name, colour: pg && pg.color,
        inStock: variants.filter((v) => v.inStock).map((v) => v.size), variants, details: details.slice(0, 16), imgs,
      });
    } catch (e) { done({ slug, err: String(e) }); }
  }, 3500);
  f.src = '/' + slug;
  document.body.appendChild(f);
});

// Reads products one at a time with a pause; parallel reads trigger HTTP 429.
window.zverifyAll = (slugs, pauseMs = 2500) => {
  const key = 'lookbook-z:products';
  const got = JSON.parse(localStorage.getItem(key) || '{}');
  window.zjob = (async () => {
    for (const s of slugs) {
      if (got[s] && !got[s].err) continue;
      got[s] = await window.zproduct(s);
      localStorage.setItem(key, JSON.stringify(got));
      await new Promise((r) => setTimeout(r, pauseMs));
    }
    localStorage.setItem(key + ':done', '1');
  })();
  return slugs.length + ' queued';
};

window.zresults = () => JSON.parse(localStorage.getItem('lookbook-z:products') || '{}');
