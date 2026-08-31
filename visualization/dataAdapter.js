export async function fetchNormalizedData() {
  const response = await fetch("http://localhost:5000/api/products");
  const rawData = await response.json();

  // Color mapping per category
  const categoryColors = {
    produce: 0x2ecc71, // Green
    meat: 0xe74c3c,    // Red
    bakery: 0xf1c40f,  // Yellow
    snacks: 0x3498db,  // Blue
    frozen: 0x9b59b6   // Purple
  };

  return rawData.map(item => {
    // Map numerical values into normalized 3D space (-20 to 20 range)
    const x = ((item.price || 0) / 50) * 40 - 20;               // X: Price ($0 - $50)
    const y = (((item.rating || 0) - 1) / 4) * 30 - 15;         // Y: Rating (1 - 5 stars)
    const z = (Math.min(item.review_count || 0, 500) / 500) * 40 - 20; // Z: Reviews (0 - 500)

    return {
      id: item.tcin,
      title: item.title,
      category: item.category,
      price: item.price,
      rating: item.rating,
      reviews: item.review_count,
      color: categoryColors[item.category] || 0xcccccc,
      position: { x, y, z }
    };
  });
}