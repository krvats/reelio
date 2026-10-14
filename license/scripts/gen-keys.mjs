// Makes the signing key pair once. Put the PRIVATE json in the SIGNING_KEY_JWK secret; the public x is published by /v1/keys.
const kp = await crypto.subtle.generateKey({ name: 'Ed25519' }, true, ['sign', 'verify']);
const priv = await crypto.subtle.exportKey('jwk', kp.privateKey);
console.log('SIGNING_KEY_JWK (keep secret):\n' + JSON.stringify(priv));
console.log('\nPUBLIC key x (safe to share, set as REELIO_LICENSE_PUBKEY in the worker):\n' + priv.x);
