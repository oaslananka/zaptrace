// Version-scoped browser acceptance runner.
import {runSmoke} from './review_studio_model_browser_smoke_shared.mjs';
await runSmoke(process.env.ZAPTRACE_017_SCREENSHOT, 'EXACT_017_SOURCE_LINKED_3D_MODEL_DIAGNOSTIC_CHROME=PASS');
