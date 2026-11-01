// Version-scoped browser acceptance runner.
import {runSmoke} from './review_studio_model_browser_smoke_shared.mjs';
await runSmoke(process.env.ZAPTRACE_019_SCREENSHOT, 'EXACT_019_SOURCE_LINKED_3D_MODEL_DIAGNOSTIC_CHROME=PASS');
