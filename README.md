# SPL Token (USDC) Signup & Recharge Handling

Documento reducido y centrado en cómo funciona el flujo de registro y recarga usando el token SPL (USDC). Todo lo irrelevante se eliminó para que el equipo (incluyendo revisores externos) entienda rápido el comportamiento.

## 1. Componentes
- Wallet del usuario (Phantom u otra compatible Solana).
- Backend principal (este servidor Flask): gestiona usuarios, saldo interno en USD (`balance_usd`).
- Microservicio de pagos (ver carpeta `payment_backend/`): valida transacción on‑chain y envía webhook firmado.

## 2. Variables Mínimas (archivo `.env`)
```
SPL_TOKEN_MINT=EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v   # USDC mainnet
PLATFORM_TREASURY_WALLET=<wallet_tesoreria>
SOLANA_RPC_URL=<rpc_url>
MIN_SIGNUP_BALANCE_USD=5
MIN_DEPOSIT_USD=1
JWT_SECRET=<jwt_shared_secret>
BASE_URL=http://localhost:8080
```

## 3. Flujo de Registro (Signup Gate por Balance On‑Chain)
1. Usuario abre `/sign-up`.
2. Frontend pide conexión de wallet (Phantom). Se obtiene `publicKey`.
3. Frontend llama `POST /api/validate_signup_balance { wallet_address }`.
4. Backend:
	 - Consulta balance SPL (token mint USDC) vía RPC.
	 - Obtiene precio live Dexscreener (filtrado estable; descarta outliers).
	 - Calcula USD = tokens * price.
	 - Si USD >= `MIN_SIGNUP_BALANCE_USD` responde `{ valid: true }`.
5. Usuario procede a crear cuenta (username/password) sólo si `valid` es `true`.

## 4. Flujo de Recarga (Depositar y Acreditar Saldo Interno)
| Paso | Actor | Descripción |
|------|-------|------------|
| 1 | Usuario | Transfiere USDC desde su wallet al `PLATFORM_TREASURY_WALLET` (lo firma localmente). |
| 2 | Frontend | Obtiene `signature` de la transacción confirmada. |
| 3 | Frontend | Envía `POST /api/deposit` `{ signature_tx, wallet_address }`. |
| 4 | Backend principal | Genera JWT y reenvía al microservicio `/api/payment/verify`. |
| 5 | Microservicio | Valida on‑chain (mint, destino, monto, idempotencia). Calcula USD con precio Dexscreener live. |
| 6 | Microservicio | Envía webhook `POST /api/webhooks/recharge_balance` con JWT firmado. |
| 7 | Backend principal | Verifica JWT; suma a `balance_usd`. |
| 8 | Usuario | Ve nuevo saldo vía `GET /api/me/balance`. |

## 5. Precio USDC
- Fuente única: Dexscreener endpoint de token.
- Para USDC se hace mediana de precios válidos en red Solana (rango permitido 0.8–1.2). Si fuera <0.8 o >1.2 se ignora.
- Endpoint diagnóstico: `GET /api/spl_price` devuelve `{ live_price_usd, cached_price_usd, db_metrics }`.

## 6. Endpoints Clave (Backend Principal)
| Método | Ruta | Uso |
|--------|------|-----|
| POST | `/api/validate_signup_balance` | Verifica balance on‑chain en USD antes de registrar. |
| POST | `/api/deposit` | Inicia verificación de depósito; proxy a microservicio. |
| POST | `/api/webhooks/recharge_balance` | Acredita saldo (JWT). |
| GET | `/api/me/balance` | Retorna saldo interno USD. |
| GET | `/api/spl_price` | Diagnóstico de precios. |

## 7. Ejemplos Frontend (JS)

### 7.1 Conectar Phantom
```html
<button id="connectWallet">Conectar Wallet</button>
<script>
let walletAddress = null;
async function connectPhantom() {
	if (!window.solana || !window.solana.isPhantom) {
		alert('Instala Phantom');
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

### 7.2 Validar Balance Para Registro
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

### 7.3 Construir y Enviar Transferencia SPL (USDC)
Ejemplo mínimo (suponiendo ya tienes amount en unidades decimales del token). Para USDC (6 decimales) convertir: `uiAmount * 10**6`.
```js
import { PublicKey, SystemProgram, Transaction } from '@solana/web3.js';
// Para tokens SPL usar @solana/spl-token (ej.: createTransferInstruction)
import { createTransferInstruction, getAssociatedTokenAddress } from '@solana/spl-token';

const MINT = new PublicKey('EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v');
const TREASURY = new PublicKey('REEMPLAZAR_TREASURY');

async function sendUsdc(uiAmount){
	const fromPub = window.solana.publicKey;
	const connection = new solanaWeb3.Connection(process.env.SOLANA_RPC_URL || 'https://api.mainnet-beta.solana.com');
	const fromAta = await getAssociatedTokenAddress(MINT, fromPub);
	const toAta = await getAssociatedTokenAddress(MINT, TREASURY);
	const amount = Math.round(uiAmount * 10 ** 6); // USDC 6 decimales
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

### 7.4 Registrar Depósito en Backend
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

### 7.5 Obtener Saldo Interno
```js
async function getInternalBalance(){
	const r = await fetch('/api/me/balance');
	const data = await r.json();
	return data.balance;
}
```

### 7.6 Flujo Completo (Pseudo)
```js
async function fullRechargeFlow(uiAmount){
	if(!walletAddress) await connectPhantom();
	const ok = await canSignup(walletAddress); // o saltar si ya registrado
	if(!ok) { alert('Balance insuficiente para requisitos mínimos'); return; }
	const sig = await sendUsdc(uiAmount);
	await registerDeposit(sig);
	setTimeout(async ()=>{
		const bal = await getInternalBalance();
		console.log('Nuevo saldo interno USD:', bal);
	}, 4000); // pequeña espera por webhook
}
```

## 8. Seguridad (Resumen)
- No se aceptan montos “USD” del cliente: el microservicio recalcula.
- Idempotencia por `signature_tx` única.
- Precio USDC filtrado (mediana, rango 0.8–1.2).
- Wallet sólo firma local; nunca se expone la clave privada.
- Webhook autenticado con JWT (`JWT_SECRET`).

## 9. Diagnóstico Rápido
| Prueba | Endpoint |
|--------|----------|
| Precio USDC | `GET /api/spl_price` |
| Saldo interno | `GET /api/me/balance` |
| Validar signup | `POST /api/validate_signup_balance` |

## 10. Mejoras Futuras (Opcional)
- Fallback de precio (Jupiter) si Dexscreener falla.
- Pre‑simulación riesgo (Blowfish) antes de firmar.
- Historial de depósitos en UI.

---
Este README está enfocado únicamente en el manejo de registro y recarga con USDC. Para lógica de generación de sitios o IA se mantienen archivos en el repositorio sin detallar aquí.

### Step 1: Create a Virtual Environment (Optional)
It is recommended to use a virtual environment to manage project dependencies:
```bash
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

### Step 2: Install Dependencies
Make sure you have the `requirements.txt` file in the project root. Then, run:
```bash
pip install -r requirements.txt
```

## Running the Server
Once the dependencies are installed, you can start the server.

The application uses Flask. To run it in development mode:
```bash
python app.py
```

For a production environment, it is recommended to use a WSGI server like Gunicorn:
```bash
gunicorn -w 4 -b 0.0.0.0:8080 app:app
```

## Publishing behavior
- On publish, a folder named after the website (sanitized) is created under `static/websites/<site>/`.
- The HTML is saved as `index.html` inside that folder.
- All multimedia elements (img, svg image, audio, video, source, poster) are downloaded to that folder and their URLs are rewritten to local paths.
- Image assets referenced from `/static/temp_media` are moved into the website folder on publish/republish. Each new image saved is charged by `PRICE_PER_IMAGE_SAVE_USD`.

## Additional Notes
-   Security: Make sure to keep your credentials and API Keys secure. Do not commit the `.env` file to your version control system.
