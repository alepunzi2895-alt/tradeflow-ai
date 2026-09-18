// Galaxy background adapted to the supplied nebula-ui visual reference.
// Spiral dust is painted once into a texture; only stars and the texture move.
(() => {
  'use strict';
  if (document.getElementById('nebula-sky')) return;
  const canvas = document.createElement('canvas');
  canvas.id = 'nebula-sky';
  canvas.setAttribute('aria-hidden', 'true');
  document.body.prepend(canvas);
  const ctx = canvas.getContext('2d', {alpha:false});
  if (!ctx) { canvas.remove(); return; }
  document.body.classList.add('has-nebula-sky');

  const reduced = matchMedia('(prefers-reduced-motion: reduce)');
  const app = document.getElementById('app');
  let width = 1, height = 1, dpr = 1, time = 0;
  let raf = 0, last = 0, paused = false;
  let seed = 90210;
  const random = () => ((seed = seed * 16807 % 2147483647) - 1) / 2147483646;
  const stars = Array.from({length:420}, () => ({
    x:random(), y:random(), r:random() < .07 ? 1.65 : .35 + random() * .8,
    phase:random() * Math.PI * 2, speed:.25 + random() * .65, depth:.2 + random(),
    warm:random() < .13
  }));

  const galaxy = document.createElement('canvas');
  galaxy.width = galaxy.height = 1400;
  const g = galaxy.getContext('2d');
  if (!g) { canvas.remove(); document.body.classList.remove('has-nebula-sky'); return; }
  const center = 700, radius = 590, tau = Math.PI * 2;
  const colors = [
    'rgba(255,236,208,.64)', 'rgba(255,196,148,.48)',
    'rgba(150,188,255,.47)', 'rgba(111,227,225,.44)',
    'rgba(255,118,178,.46)', 'rgba(236,242,255,.63)'
  ];
  function glow(context, x, y, r, stops) {
    const gradient = context.createRadialGradient(x,y,0,x,y,r);
    stops.forEach(([at,color]) => gradient.addColorStop(at,color));
    context.fillStyle = gradient;
    context.fillRect(x-r,y-r,r*2,r*2);
  }
  glow(g,center,center,radius*.8,[[0,'#ffdebb90'],[.18,'#e2a27730'],[.5,'#7a80d80c'],[1,'#00000000']]);
  for (let i=0; i<7800; i++) {
    const distance = Math.pow(random(),1.3);
    const spread = random()<.28 ? 2.6 : 1;
    const angle = distance<.09 ? random()*tau : (i%2)*Math.PI + distance*5.4 + (random()-.5)*(.35+.8*(1-distance))*spread;
    const q = random();
    const group = distance<.09 ? 0 : distance<.26 ? (q<.72?1:5) : (q<.6?2:q<.76?3:q<.84?4:q<.93?5:1);
    const size = (group===0?1.25:.45)+random()*1.3;
    g.fillStyle = colors[group];
    g.fillRect(center+Math.cos(angle)*distance*radius,center+Math.sin(angle)*distance*radius,size,size);
  }
  // Diffuse halo and darker dust lanes give the arms depth without a solid disc.
  for (let i=0; i<1700; i++) {
    const distance=random()*1.13, angle=random()*tau;
    g.fillStyle='rgba(140,160,230,.12)';
    g.fillRect(center+Math.cos(angle)*distance*radius,center+Math.sin(angle)*distance*radius,1+random(),1+random());
  }
  for (let i=0; i<1400; i++) {
    const distance=.12+random()*.7;
    const angle=(i%2)*Math.PI+distance*5.4+.22+(random()-.5)*.16;
    g.fillStyle='rgba(3,5,11,.34)';
    g.fillRect(center+Math.cos(angle)*distance*radius,center+Math.sin(angle)*distance*radius,2,3);
  }
  glow(g,center,center,radius*.075,[[0,'#fffaf0f0'],[.25,'#ffddb87a'],[1,'#00000000']]);

  const haze = document.createElement('canvas');
  const hctx = haze.getContext('2d');
  function resize() {
    width = Math.max(1,innerWidth); height = Math.max(1,innerHeight);
    dpr = Math.min(devicePixelRatio||1,2,Math.sqrt(3000000/(width*height)));
    canvas.width = Math.round(width*dpr); canvas.height = Math.round(height*dpr);
    if (hctx) {
      // Low resolution is intentional for smooth, cached atmospheric light.
      haze.width = Math.ceil(width*.5); haze.height = Math.ceil(height*.5);
      for (const [x,y,r,color] of [[.74,.28,.4,'rgba(90,70,170,.22)'],[.5,.72,.36,'rgba(30,110,140,.16)'],[.12,.18,.3,'rgba(160,60,120,.10)']]) {
        glow(hctx,x*haze.width,y*haze.height,r*Math.max(haze.width,haze.height),[[0,color],[1,'#00000000']]);
      }
    }
    paint();
  }
  function paint() {
    ctx.setTransform(dpr,0,0,dpr,0,0);
    ctx.globalCompositeOperation='source-over';
    ctx.fillStyle='#04060e'; ctx.fillRect(0,0,width,height);
    if(hctx) ctx.drawImage(haze,0,0,width,height);
    const mobile=width<650;
    const starCount=mobile?210:stars.length;
    for(let i=0;i<starCount;i++) {
      const star=stars[i];
      const x=(star.x*width+time*star.depth*1.6)%width;
      const y=star.y*height;
      const alpha=.22+.65*(.5+.5*Math.sin(time*star.speed+star.phase));
      ctx.fillStyle=star.warm?`rgba(255,225,189,${alpha})`:`rgba(224,235,255,${alpha})`;
      ctx.fillRect(x,y,star.r,star.r);
      if(star.r>1.5) {
        ctx.globalAlpha=alpha*.2;
        ctx.fillRect(x-2,y+.5,6,.5); ctx.fillRect(x+.5,y-2,.5,6);
        ctx.globalAlpha=1;
      }
    }
    const size=(mobile?width*1.15:Math.min(width,height)*.88)*2;
    const cx=width*(mobile?.68:.72), cy=height*(mobile?.43:.34);
    ctx.save();
    ctx.translate(cx,cy); ctx.rotate(-.38); ctx.scale(1,.36); ctx.rotate(time*.009);
    ctx.globalCompositeOperation='lighter'; ctx.globalAlpha=mobile?.72:.86;
    ctx.drawImage(galaxy,-size/2,-size/2,size,size);
    ctx.restore();
    // A brief, infrequent streak; no flashes and no motion in reduced-motion mode.
    const phase=time%19;
    if(!reduced.matches && phase>8 && phase<9.2) {
      const progress=(phase-8)/1.2;
      const x=width*(.1+progress*.42), y=height*(.1+progress*.17);
      const length=Math.min(110,width*.17);
      const gradient=ctx.createLinearGradient(x,y,x-length,y-length*.4);
      gradient.addColorStop(0,`rgba(226,240,255,${Math.sin(progress*Math.PI)*.65})`);
      gradient.addColorStop(1,'rgba(226,240,255,0)');
      ctx.strokeStyle=gradient; ctx.lineWidth=.9;
      ctx.beginPath(); ctx.moveTo(x,y); ctx.lineTo(x-length,y-length*.4); ctx.stroke();
    }
    // Keep the edges quiet, matching Nebula's continuous vignette.
    const shade=ctx.createRadialGradient(width*.55,height*.4,width*.12,width*.55,height*.4,Math.max(width,height)*.8);
    shade.addColorStop(0,'rgba(4,6,14,0)'); shade.addColorStop(1,'rgba(4,6,14,.72)');
    ctx.fillStyle=shade; ctx.fillRect(0,0,width,height);
  }
  function canMove() { return !paused && !document.hidden && !reduced.matches && (!app || app.style.display!=='none'); }
  function frame(now) {
    raf=0;
    if(!canMove()) return;
    if(!last || now-last>=1000/30) {
      if(last)time+=Math.min((now-last)/1000,.1);
      last=now; paint();
    }
    raf=requestAnimationFrame(frame);
  }
  function sync() {
    cancelAnimationFrame(raf); raf=0; last=0;
    canvas.dataset.motion=canMove()?'running':'still';
    paint();
    if(canMove())raf=requestAnimationFrame(frame);
  }
  window.NebulaSky={setPaused(value){paused=Boolean(value);sync();}};
  new ResizeObserver(resize).observe(canvas);
  if(app)new MutationObserver(sync).observe(app,{attributes:true,attributeFilter:['style']});
  document.addEventListener('visibilitychange',sync);
  reduced.addEventListener('change',sync);
  window.addEventListener('resize',resize,{passive:true});
  resize(); sync();
})();
