<script setup>
// A still preview of one VU meter skin, drawn like the kiosk's own preview in
// Settings → VU meter (native-ui-qt/qml/VuPanel.qml with levels [62, 55]):
// under.png, the backlight fully lit, the peak needle a little above the
// needle, the needles, over.png. The skin's files come from api_server
// (/vu_skin/<id>/<file>); the geometry is skin.json's, so an SVG in the
// skin's own pixel space places everything exactly where the kiosk does.
import { ref, computed, watch, onMounted, onBeforeUnmount } from 'vue';

const props = defineProps({
  skinId: { type: String, required: true },
  levels: { type: Array, default: () => [62, 55] },
});

const SAFE = /^[a-z0-9][a-z0-9._-]*\.(png|jpg)$/;
const cache = (globalThis.__vuSkinCache ||= new Map());

const skin = ref(null);
const box = ref(null);
const boxWidth = ref(0);
let ro = null;

async function load(id) {
  skin.value = null;
  if (!cache.has(id)) {
    cache.set(id, fetch(`/api/system/vu_skin/${encodeURIComponent(id)}/skin.json`, { credentials: 'same-origin' })
      .then((r) => (r.ok ? r.json() : null))
      .catch(() => null));
  }
  const s = await cache.get(id);
  if (props.skinId !== id) return;
  if (!s || !Array.isArray(s.size) || !Array.isArray(s.meters) || s.meters.length < 2
      || !Array.isArray(s.angles) || !s.needle || !SAFE.test(s.under || '') || !SAFE.test(s.over || '')
      || (s.needle.image && !SAFE.test(s.needle.image))) return;
  skin.value = s;
}
watch(() => props.skinId, load, { immediate: true });

onMounted(() => {
  ro = new ResizeObserver((e) => { boxWidth.value = e[0].contentRect.width; });
  if (box.value) ro.observe(box.value);
});
onBeforeUnmount(() => ro && ro.disconnect());

const url = (name) => `/api/system/vu_skin/${encodeURIComponent(props.skinId)}/${name}`;
// the box is the kiosk's 1280x675 card; the artwork keeps its shape inside
const sw = computed(() => (skin.value ? skin.value.size[0] : 1280));
const sh = computed(() => (skin.value ? skin.value.size[1] : 675));
// screen pixels per skin pixel, for the drawn needle's minimum width
const ps = computed(() => (boxWidth.value ? Math.min(boxWidth.value / sw.value, (boxWidth.value * 675 / 1280) / sh.value) : 0.25));
const fx = computed(() => (skin.value && skin.value.effects && typeof skin.value.effects === 'object' ? skin.value.effects : {}));

function angle(level) {
  const [a0, a1] = skin.value.angles;
  return a0 + (a1 - a0) * Math.max(0, Math.min(100, level)) / 100;
}
function needles(i) {
  const s = skin.value;
  const out = [];
  const pk = fx.value.peakNeedle;
  if (pk && (!pk.image || SAFE.test(pk.image))) {
    out.push({ key: 'peak', n: { color: '#d32f2f', width: 2, minWidth: 1.5, height: s.needle.height || 300, ...pk },
               deg: angle(Math.min(100, props.levels[i] + 14)) });
  }
  out.push({ key: 'needle', n: s.needle, deg: angle(props.levels[i]) });
  return out;
}
const drawnWidth = (n) => Math.max((n.minWidth || 0) / ps.value, n.width || 0);
const backlight = computed(() => (fx.value.backlight && SAFE.test(fx.value.backlight.image || '') ? fx.value.backlight.image : ''));
</script>

<template>
  <div ref="box" class="vu-skin-preview">
    <svg v-if="skin" :viewBox="`0 0 ${sw} ${sh}`" preserveAspectRatio="xMidYMid meet" aria-hidden="true">
      <image :href="url(skin.under)" x="0" y="0" :width="sw" :height="sh" />
      <image v-if="backlight" :href="url(backlight)" x="0" y="0" :width="sw" :height="sh" />
      <g v-for="(m, i) in skin.meters.slice(0, 2)" :key="i" :transform="`translate(${m[0]} ${m[1]})`">
        <g v-for="nd in needles(i)" :key="nd.key" :transform="`rotate(${nd.deg})`">
          <image v-if="nd.n.image" :href="url(nd.n.image)"
                 :x="-(nd.n.pivotX || 0)" :y="-(nd.n.pivotY || 0)" :width="nd.n.width || 0" :height="nd.n.height || 0" />
          <template v-else>
            <rect :x="-drawnWidth(nd.n) / 2" :y="-(nd.n.height || 0)" :width="drawnWidth(nd.n)" :height="nd.n.height || 0"
                  :fill="nd.n.color || '#111111'" :class="{ shadow: nd.n.shadow }" />
            <circle v-if="(nd.n.cap || 0) > 0" :r="nd.n.cap / 2" :fill="nd.n.color || '#111111'" />
          </template>
        </g>
      </g>
      <image :href="url(skin.over)" x="0" y="0" :width="sw" :height="sh" />
    </svg>
  </div>
</template>
