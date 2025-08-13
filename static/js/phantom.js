// New Phantom wallet integration for asynchronous deposit verification
(function(){
  const el = id => document.getElementById(id);
  const connectBtn = el('connectWalletBtn');
  const walletAddressDiv = el('walletAddress');
  const signupRequirement = el('signupRequirement');
  const depositSection = el('deposit-section');
  const amountInput = el('amountTokens');
  const sendBtn = el('sendDepositBtn');
  const statusDiv = el('depositStatus');
  const mintSpan = el('mintAddress');
  const treasurySpan = el('treasuryAddress');
  const estUsdSpan = el('estimatedUsd');
  const balanceDiv = el('currentBalance');
  const txSigInput = el('txSignature');
  const minDepositUsd = el('minDepositUsd');
  const minDepositTokens = el('minDepositTokens');

  let publicKey = null;
  let tokenConfig = null;
  let pollTimer = null;
  let lastBalance = null;

  async function fetchTokenConfig(){
    try {
      const r = await fetch('/api/token_config');
      if(!r.ok) return;
      tokenConfig = await r.json();
      if(tokenConfig.mint_address) mintSpan.textContent = tokenConfig.mint_address;
      if(tokenConfig.treasury) treasurySpan.textContent = tokenConfig.treasury;
      if(tokenConfig.min_deposit_tokens && minDepositTokens) minDepositTokens.textContent = tokenConfig.min_deposit_tokens;
      if(tokenConfig.min_deposit_usd && minDepositUsd) minDepositUsd.textContent = '$'+tokenConfig.min_deposit_usd;
      updateEstimate();
    } catch(e){ console.warn('token_config fetch failed', e); }
  }

  async function fetchBalance(){
    try {
      const r = await fetch('/api/me/balance');
      if(!r.ok) return;
      const d = await r.json();
      const b = (d.balance_usd && !isNaN(d.balance_usd)) ? Number(d.balance_usd).toFixed(2) : d.balance_usd;
      if(balanceDiv){
        if(lastBalance !== null && b !== lastBalance && statusDiv.textContent.includes('Waiting')){
          statusDiv.textContent = 'Deposit credited!';
          if(pollTimer) clearInterval(pollTimer);
        }
        balanceDiv.textContent = '$'+b;
        lastBalance = b;
      }
    } catch(e){}
  }

  function updateEstimate(){
    if(!tokenConfig) return;
    const amt = parseFloat(amountInput?.value||'0');
    const price = tokenConfig.token_price || 0;
    const usd = amt * price;
    if(estUsdSpan) estUsdSpan.textContent = usd.toFixed(2);
  }
  amountInput?.addEventListener('input', updateEstimate);

  async function connectPhantom(){
    if(!window.solana || !window.solana.isPhantom){
      alert('Phantom wallet not found. Install it to continue.');
      return;
    }
    try {
      const resp = await window.solana.connect();
      publicKey = resp.publicKey.toString();
      walletAddressDiv.textContent = publicKey;
      signupRequirement.textContent = 'Wallet connected – ensure it is linked to your account.';
      depositSection.style.display = 'block';
      fetchBalance();
    } catch(e){
      console.error(e);
      alert('Connection rejected');
    }
  }

  async function submitDeposit(){
    if(!publicKey){ alert('Connect wallet first'); return; }
    if(!tokenConfig){ alert('Token config not loaded'); return; }
    const amountTokens = parseFloat(amountInput.value||'0');
    if(!amountTokens || amountTokens<=0){ statusDiv.textContent='Enter a valid token amount.'; return; }
    const sig = txSigInput.value.trim();
    if(!sig){ statusDiv.textContent='Paste the transaction signature.'; return; }
    const amountUsd = parseFloat(estUsdSpan.textContent)||null;
    statusDiv.textContent='Submitting deposit...';
    try {
      const res = await fetch('/api/deposit', {
        method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({ signature_tx: sig, amount_tokens: amountTokens, amount_usd: amountUsd, wallet_address: publicKey, mint_address: tokenConfig.mint_address })
      });
      const data = await res.json().catch(()=>({}));
      if(!res.ok){
        statusDiv.textContent = 'Error: '+ (data.message||data.error||'Unknown');
        return;
      }
      statusDiv.textContent='Deposit submitted. Waiting for verification & credit...';
      if(pollTimer) clearInterval(pollTimer);
      pollTimer = setInterval(fetchBalance, 4000);
    } catch(e){
      console.error(e);
      statusDiv.textContent='Network error sending deposit.';
    }
  }

  connectBtn?.addEventListener('click', connectPhantom);
  sendBtn?.addEventListener('click', submitDeposit);

  fetchTokenConfig();
  fetchBalance();
})();
