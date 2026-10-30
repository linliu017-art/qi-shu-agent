import {spawnSync} from 'node:child_process';
const result=spawnSync(process.execPath,['--experimental-strip-types','--test','tests/client.test.ts'],{stdio:'inherit'});
process.exit(result.status??1);
