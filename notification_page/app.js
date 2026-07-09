// ------------------------------------------
// Smart Farm Registration Page
// ------------------------------------------

const DEVICE_ID = "esp32_001";

// Your Render backend
const API_URL =
    "https://smartfarm-4z48.onrender.com/register_subscription";

const registerBtn = document.getElementById("registerBtn");
const emailInput = document.getElementById("email");
const statusDiv = document.getElementById("status");

registerBtn.addEventListener("click", async () => {

    const email = emailInput.value.trim();

    if (email === "") {

        statusDiv.innerHTML =
            "❌ Please enter your email address.";

        return;
    }

    // Simple email validation
    const emailRegex =
        /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

    if (!emailRegex.test(email)) {

        statusDiv.innerHTML =
            "❌ Please enter a valid email address.";

        return;
    }

    statusDiv.innerHTML =
        "Registering...";

    try {

        const response = await fetch(API_URL, {

            method: "POST",

            headers: {
                "Content-Type": "application/json"
            },

            body: JSON.stringify({

                email: email,

                device_id: DEVICE_ID

            })

        });

        const result = await response.json();

        console.log(result);

        if (!response.ok) {

            statusDiv.innerHTML =
                "❌ " + (result.error || "Registration failed.");

            return;
        }

        statusDiv.innerHTML =
            "✅ Successfully registered! Future farm advisories will be sent to:<br><br><strong>"
            + email +
            "</strong>";

        emailInput.value = "";

    }

    catch (err) {

        console.error(err);

        statusDiv.innerHTML =
            "❌ Unable to contact the registration server.";

    }

});