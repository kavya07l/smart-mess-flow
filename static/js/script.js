// Update the dashboard counters and progress bars without a full page reload.
document.addEventListener("DOMContentLoaded", () => {
  const dashboard = document.getElementById("dashboard-stats");
  if (dashboard) {
    const refreshDashboard = async () => {
      try {
        const response = await fetch(dashboard.dataset.dashboardUrl, {
          headers: { Accept: "application/json" },
        });
        if (!response.ok) throw new Error(`Dashboard update failed (${response.status})`);
        const data = await response.json();
        document.getElementById("inside-count").textContent = data.inside_count;
        document.getElementById("waiting-time").textContent = data.waiting_minutes;
        data.slots.forEach((slot) => {
          const card = document.querySelector(`.slot-card[data-slot-id="${slot.slot_id}"]`);
          if (!card) return;
          card.querySelector(".seats-value").textContent = `${slot.seats_left} seats left`;
          card.querySelector(".booked-count").textContent = slot.booked;
          card.querySelector(".capacity-count").textContent = slot.capacity;
          card.querySelector(".progress-fill").style.width =
            `${Math.min(100, (slot.booked * 100) / slot.capacity)}%`;
        });
      } catch (error) {
        console.error(error);
      }
    };
    window.setInterval(refreshDashboard, 10000);
  }

  const mealSelect = document.getElementById("meal");
  const slotSelect = document.getElementById("slot_id");
  if (mealSelect && slotSelect) {
    const cards = [...document.querySelectorAll(".available-slot")];
    const updateSlots = () => {
      const meal = mealSelect.value;
      slotSelect.replaceChildren();
      const initial = document.createElement("option");
      initial.value = "";
      initial.textContent = meal ? "Choose a time slot" : "Select a meal first";
      slotSelect.append(initial);
      cards.filter((card) => card.dataset.meal === meal).forEach((card) => {
        const option = document.createElement("option");
        option.value = card.dataset.slotId;
        option.textContent = `${card.querySelector("h3").textContent} · ${card.dataset.seats} seats left`;
        option.disabled = Number(card.dataset.seats) <= 0;
        slotSelect.append(option);
      });
    };
    mealSelect.addEventListener("change", updateSlots);
  }
});
