#!/bin/bash
# PTS Analysis Script with Claude API

# Load environment variables from shell config
if [ -f ~/.zshrc ]; then
    source ~/.zshrc
fi

echo "🚀 Starting PTS Analysis with Claude API..."
echo "=================================="

# Check if API key is set
if [ -z "$ANTHROPIC_API_KEY" ]; then
    echo "❌ Error: ANTHROPIC_API_KEY not found"
    echo "Please set it in your ~/.zshrc file"
    exit 1
fi

echo "✓ API Key found"
echo ""

# Run the analysis
python3 fetch_and_analyze_pts.py

echo ""
echo "✅ Analysis complete!"
echo "View results at: http://localhost:5001"
