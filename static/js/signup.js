document.addEventListener('DOMContentLoaded', function() {
    document.getElementById('signup-form').addEventListener('submit', async (event) => {
        event.preventDefault();
        const username = document.getElementById('username').value;
        const password = document.getElementById('password').value;
        const errorMessage = document.getElementById('error-message');

        try {
            const response = await fetch('/confirm_and_signup', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ username, password }),
            });

            const result = await response.json();

            if (response.ok && result.success) {
                Swal.fire({
                    title: (window.i18n && i18n.t) ? i18n.t('signup_success_title') : 'Registration Successful!',
                    text: (window.i18n && i18n.t) ? i18n.t('signup_success_text') : 'You will be redirected to the login page.',
                    icon: 'success',
                    timer: 2000,
                    showConfirmButton: false,
                }).then(() => { window.location.href = '/login'; });
            } else {
                const title = (window.i18n && i18n.t) ? i18n.t('error_title') : 'Error';
                errorMessage.textContent = `${title}: ${result.error}`;
            }
        } catch (error) {
            errorMessage.textContent = (window.i18n && i18n.t) ? i18n.t('network_error') : 'An unexpected error occurred. Please try again.';
            console.error('Signup error:', error);
        }
    });
});
