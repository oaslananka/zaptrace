// Version-scoped historical native Chrome model acceptance.
import {runSmoke} from './review_studio_model_browser_smoke_shared.mjs';
await runSmoke(process.env.ZAPTRACE_015_SCREENSHOT, 'EXACT_015_SOURCE_LINKED_3D_MODEL_DIAGNOSTIC_CHROME=PASS', true);
