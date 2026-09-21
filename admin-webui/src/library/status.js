// /api/library/status, asked once per page load and shared by every screen:
// whether this device holds the files (a device following another Lyrion
// does not) and which formats it can write.
import { ref } from 'vue';
import { lib } from './libraryApi.js';

const status = ref(null);
let pending = null;

export function useLibraryStatus() {
  if (!status.value && !pending) {
    pending = lib.status().then((r) => {
      if (r.ok && r.data && typeof r.data === 'object') status.value = r.data;
      pending = null;
    });
  }
  return { status };
}
