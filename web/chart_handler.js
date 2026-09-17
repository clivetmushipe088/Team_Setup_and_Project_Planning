// Load the dashboard data and show it on the page
fetch("data/processed/dashboard.json")
  .then((res) => res.json())
  .then((data) => {
    document.getElementById("status").textContent = "Data loaded";
    console.log(data);
    // TODO: draw charts and table
  })
  .catch(() => {
    document.getElementById("status").textContent = "No data yet, run the ETL first";
  });
