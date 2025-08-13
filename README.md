# SPL Token (USDC) Signup & Recharge Handling
   
Concise document explaining how the signup (gate) and balance recharge flow works using the USDC SPL token. Unrelated details were removed so reviewers can understand behavior quickly.

## 1. Components
- User wallet (Phantom or any Solana‑compatible wallet).
- Main backend (this Flask server): manages users and an internal USD balance (`balance_usd`).
- Payment microservice (see `payment_backend/`): validates the on‑chain transaction and dispatches a signed webhook.

## 2. Minimum Environment Variables (`.env`)
```
SPL_TOKEN_MINT=EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v   # USDC mainnet
PLATFORM_TREASURY_WALLET=<treasury_wallet>
SOLANA_RPC_URL=<rpc_url>
MIN_SIGNUP_BALANCE_USD=5
MIN_DEPOSIT_USD=1
JWT_SECRET=<jwt_shared_secret>
BASE_URL=http://localhost:8080
```

## 3. Signup Flow (On‑Chain Balance Gate)
1. User opens `/sign-up`.
2. Frontend requests wallet connection (Phantom). Gets `publicKey`.
3. Frontend calls `POST /api/validate_signup_balance { wallet_address }`.
4. Backend:
	 - Fetches SPL token balance (USDC mint) via RPC.
	 - Fetches live Dexscreener price (stable filter; discards outliers).
	 - Computes `usd = token_amount * price`.
	 - If `usd >= MIN_SIGNUP_BALANCE_USD` responds `{ valid: true }`.
5. User can create account (username/password) only if `valid` is true.

## 4. Recharge (Deposit & Credit Internal Balance)
| Step | Actor | Description |
|------|-------|-------------|
| 1 | User | Sends USDC from their wallet to `PLATFORM_TREASURY_WALLET` (signed locally). |
| 2 | Frontend | Obtains confirmed transaction `signature`. |
| 3 | Frontend | Sends `POST /api/deposit` `{ signature_tx, wallet_address }`. |
| 4 | Main backend | Issues JWT and proxies to microservice `/api/payment/verify`. |
| 5 | Microservice | Validates on‑chain (mint, destination, amount, idempotency). Computes USD with live Dexscreener price. |
| 6 | Microservice | Sends webhook `POST /api/webhooks/recharge_balance` with signed JWT. |
| 7 | Main backend | Verifies JWT; increments `balance_usd`. |
| 8 | User | Sees new balance via `GET /api/me/balance`. |

## 5. USDC Price Logic
- Single source: Dexscreener token endpoint.
- For USDC: median of valid Solana prices within 0.8–1.2 range (ignore out-of-range values).
- Diagnostic endpoint: `GET /api/spl_price` returns `{ live_price_usd, cached_price_usd, db_metrics }`.

## 6. Key Endpoints (Main Backend)
| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/validate_signup_balance` | Check on‑chain USD balance before signup. |
| POST | `/api/deposit` | Start deposit verification; proxy to microservice. |
| POST | `/api/webhooks/recharge_balance` | Credit internal balance (JWT). |
| GET | `/api/me/balance` | Return internal USD balance. |
| GET | `/api/spl_price` | Price diagnostics. |

## 7. Frontend Examples (JS)

### 7.1 Connect Phantom
```html
<button id="connectWallet">Connect Wallet</button>
<script>
let walletAddress = null;
async function connectPhantom() {
	if (!window.solana || !window.solana.isPhantom) {
		alert('Install Phantom');
		return;
	}
	try {
		const resp = await window.solana.connect({ onlyIfTrusted: false });
		walletAddress = resp.publicKey.toString();
		console.log('Wallet:', walletAddress);
	} catch(e){ console.error(e); }
}
document.getElementById('connectWallet').onclick = connectPhantom;
</script>
```

### 7.2 Validate Balance for Signup
```js
async function canSignup(addr){
	const r = await fetch('/api/validate_signup_balance', {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ wallet_address: addr })
	});
	const data = await r.json();
	if (!r.ok) { console.error(data); return false; }
	console.log('Signup check:', data);
	return data.valid;
}
```

### 7.3 Build & Send SPL (USDC) Transfer
Minimal example (assuming you already have amount in token decimal units). For USDC (6 decimals): `uiAmount * 10**6`.
```js
import { PublicKey, SystemProgram, Transaction } from '@solana/web3.js';
// For SPL tokens use @solana/spl-token (e.g. createTransferInstruction)
import { createTransferInstruction, getAssociatedTokenAddress } from '@solana/spl-token';

const MINT = new PublicKey('EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v');
const TREASURY = new PublicKey('REPLACE_TREASURY');

async function sendUsdc(uiAmount){
	const fromPub = window.solana.publicKey;
	const connection = new solanaWeb3.Connection(process.env.SOLANA_RPC_URL || 'https://api.mainnet-beta.solana.com');
	const fromAta = await getAssociatedTokenAddress(MINT, fromPub);
	const toAta = await getAssociatedTokenAddress(MINT, TREASURY);
	const amount = Math.round(uiAmount * 10 ** 6); // USDC 6 decimals
	const ix = createTransferInstruction(fromAta, toAta, fromPub, amount);
	const tx = new Transaction().add(ix);
	tx.feePayer = fromPub;
	tx.recentBlockhash = (await connection.getLatestBlockhash()).blockhash;
	const signed = await window.solana.signTransaction(tx);
	const sig = await connection.sendRawTransaction(signed.serialize());
	await connection.confirmTransaction(sig, 'confirmed');
	return sig;
}
```

### 7.4 Register Deposit with Backend
```js
async function registerDeposit(signature){
	const r = await fetch('/api/deposit', {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({
			signature_tx: signature,
			wallet_address: walletAddress
		})
	});
	const data = await r.json();
	console.log('Deposit submit response:', data);
	return data;
}
```

### 7.5 Get Internal Balance
```js
async function getInternalBalance(){
	const r = await fetch('/api/me/balance');
	const data = await r.json();
	return data.balance;
}
```

### 7.6 Full Recharge Flow (Pseudo)
```js
async function fullRechargeFlow(uiAmount){
	if(!walletAddress) await connectPhantom();
	const ok = await canSignup(walletAddress); // or skip if already registered
	if(!ok) { alert('Insufficient balance for minimum requirements'); return; }
	const sig = await sendUsdc(uiAmount);
	await registerDeposit(sig);
	setTimeout(async ()=>{
		const bal = await getInternalBalance();
		console.log('New internal USD balance:', bal);
	}, 4000); // small wait for webhook
}
```

## 8. Security Summary
- Client doesn’t submit arbitrary USD amounts: microservice recalculates.
- Idempotency via unique `signature_tx`.
- USDC price filtered (median, 0.8–1.2 band).
- Wallet signs locally; private key never leaves client.
- Webhook authenticated with JWT (`JWT_SECRET`).

## 9. Quick Diagnostics
| Test | Endpoint |
|------|----------|
| USDC price | `GET /api/spl_price` |
| Internal balance | `GET /api/me/balance` |
| Validate signup | `POST /api/validate_signup_balance` |

