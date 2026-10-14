// Test helper: prints {x, token} signed like the real service. Usage: node mint-token.mjs '<claims-json>'
import { importSigner, signToken } from '../src/crypto.js';
const kp = await crypto.subtle.generateKey({ name: 'Ed25519' }, true, ['sign', 'verify']);
const priv = await crypto.subtle.exportKey('jwk', kp.privateKey);
const claims = JSON.parse(process.argv[2] || '{}');
console.log(JSON.stringify({ x: priv.x, token: await signToken(await importSigner(priv), 'k1', claims) }));
