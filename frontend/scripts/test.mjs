import {spawnSync} from 'node:child_process';
const result=spawnSync(process.execPath,['--experimental-strip-types','--test','tests/client.test.ts','tests/office.test.ts','tests/markdown-safety.test.ts','tests/native-editor.test.ts'],{stdio:'inherit'});
process.exit(result.status??1);
