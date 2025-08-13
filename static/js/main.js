// Lógica de botones
    const callBtn   = document.getElementById('callBtn');
    const hangupBtn = document.getElementById('hangupBtn');
    const muteBtn   = document.getElementById('muteBtn');
    const muteIcon  = muteBtn.querySelector('i');
    let isMuted     = false;

    callBtn.addEventListener('click', () => {
      muteBtn.classList.remove('hidden');
      hangupBtn.classList.remove('hidden');
      callBtn.classList.add('hidden');
    });

    hangupBtn.addEventListener('click', () => {
      muteBtn.classList.add('hidden');
      hangupBtn.classList.add('hidden');
      callBtn.classList.remove('hidden');
      // reset mute
      isMuted = false;
      muteIcon.classList.replace('fa-microphone-slash','fa-microphone');
    });

    muteBtn.addEventListener('click', () => {
      isMuted = !isMuted;
      if (isMuted) {
        muteIcon.classList.replace('fa-microphone','fa-microphone-slash');
      } else {
        muteIcon.classList.replace('fa-microphone-slash','fa-microphone');
      }
    });
