# Project Documentation

# Project Structure
```
energyLiveData/
├── docs/
│   ├── energylivedata_dashboard.md
│   ├── energylivedata_overview.md
│   ├── energylivedata_research.md
│   ├── energylivedata_technical.md
│   ├── energyzero_vs_frank_energie.md
├── LICENSE
├── README.md
```

# docs\energylivedata_dashboard.md
```markdown
# energyLiveData - Dashboard Integration Guide

## Integration Overview

This document outlines how **Augur** integrates with **energyLiveData** using **Energy Zero** consumer pricing data to provide comprehensive market visualization, real-time monitoring, and forecast validation capabilities.

## Architecture Integration

### Data Flow Integration
```
energydatahub (Forecasts) ──┐
                            ├──► Augur
energyLiveData (Actual) ────┘
    │
    └── Energy Zero Consumer Pricing
                            
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│ energydatahub   │    │ energyLiveData   │    │energyDataDashb. │
│                 │    │                  │    │                 │
│ Daily forecasts │    │ 15-min actual    │    │ • Forecast vs   │
│ Energy, weather │───▶│ Energy, weather  │───▶│   Actual        │
│ Solar, air qual │    │ Energy Zero data │    │ • Market gaps   │
│                 │    │ Grid status      │    │ • Live alerts   │
└─────────────────┘    └──────────────────┘    └─────────────────┘
```

### Dashboard Enhancement Strategy
```
Current Augur:
├── Forecast visualization (static daily updates)
├── Price threshold analysis
└── Basic statistics

Enhanced with energyLiveData + Energy Zero:
├── Forecast vs Actual comparison
├── Real-time market transparency
├── Energy Zero vs wholesale analysis  
├── Live grid status monitoring
├── Dynamic accuracy metrics
├── Gas-electricity correlation
└── Predictive alerts system
```

## Energy Zero Data Integration

### Enhanced Data Loading
```javascript
// Enhanced data loading with Energy Zero integration
class EnhancedEnergyDashboard {
    constructor() {
        this.dataSources = {
            forecasts: '/data/energy_price_forecast.json',     // energydatahub
            liveData: '/data/live/current_snapshot.json',      // energyLiveData
            rolling24h: '/data/live/rolling_24h.json',         // energyLiveData
            marketAnalysis: '/data/live/market_analysis.json', // energyLiveData
            energyZeroHistory: '/data/live/energyzero_24h.json' // Energy Zero historical
        };
        this.refreshInterval = 15 * 60 * 1000; // 15 minutes
        this.init();
    }
    
    async loadAllData() {
        const [forecasts, liveData, rolling24h, marketAnalysis, energyZeroHistory] = await Promise.all([
            this.fetchData(this.dataSources.forecasts),
            this.fetchData(this.dataSources.liveData),
            this.fetchData(this.dataSources.rolling24h),
            this.fetchData(this.dataSources.marketAnalysis),
            this.fetchData(this.dataSources.energyZeroHistory)
        ]);
        
        return {
            forecasts: await this.decryptData(forecasts),
            liveData: await this.decryptData(liveData),
            rolling24h: await this.decryptData(rolling24h),
            marketAnalysis: await this.decryptData(marketAnalysis),
            energyZeroHistory: await this.decryptData(energyZeroHistory)
        };
    }
}
```

### Energy Zero Data Processing
```javascript
class EnergyZeroDataProcessor {
    processEnergyZeroSnapshot(snapshot) {
        return {
            timestamp: new Date(snapshot.timestamp),
            
            // Energy Zero consumer pricing
            consumer: {
                electricityTotal: snapshot.consumer_price_total,
                electricityEnergy: snapshot.consumer_price_energy,
                gasPrice: snapshot.gas_price,
                networkCosts: snapshot.network_costs,
                taxesAndFees: snapshot.taxes_and_fees,
                priceGap: snapshot.price_gap,
                priceGapPercentage: snapshot.price_gap_percentage
            },
            
            // Wholesale market data
            wholesale: {
                price: snapshot.wholesale_price,
                load: snapshot.actual_load,
                renewableShare: snapshot.renewable_share,
                imbalancePrice: snapshot.imbalance_price
            },
            
            // Environmental data
            weather: {
                temperature: snapshot.temperature,
                windSpeed: snapshot.wind_speed,
                solarIrradiance: snapshot.solar_irradiance,
                cloudCover: snapshot.cloud_cover
            },
            
            // Air quality
            airQuality: {
                aqi: snapshot.aqi,
                pm25: snapshot.pm25,
                no2: snapshot.no2
            }
        };
    }
    
    compareEnergyZeroWithForecast(forecast, actual) {
        const comparison = {};
        
        // Energy Zero vs forecast comparison
        if (forecast.price && actual.consumer.electricityTotal) {
            const forecastConsumer = forecast.price + 150; // Estimated consumer markup
            const error = Math.abs(forecastConsumer - actual.consumer.electricityTotal);
            const errorPercentage = (error / forecastConsumer) * 100;
            
            comparison.consumerPrice = {
                forecast: forecastConsumer,
                actualEnergyZero: actual.consumer.electricityTotal,
                error: error,
                errorPercentage: errorPercentage,
                accuracy: Math.max(0, 100 - errorPercentage)
            };
        }
        
        // Wholesale price comparison
        if (forecast.price && actual.wholesale.price) {
            const error = Math.abs(forecast.price - actual.wholesale.price);
            const errorPercentage = (error / forecast.price) * 100;
            
            comparison.wholesalePrice = {
                forecast: forecast.price,
                actual: actual.wholesale.price,
                error: error,
                errorPercentage: errorPercentage,
                accuracy: Math.max(0, 100 - errorPercentage)
            };
        }
        
        return comparison;
    }
}
```

## Enhanced Dashboard Components

### Energy Zero Status Panel
```javascript
class EnergyZeroStatusPanel {
    render(liveData) {
        return `
        <div class="live-status-grid">
            <!-- Wholesale Market Status -->
            <div class="status-card wholesale">
                <h3>Wholesale Market</h3>
                <div class="price-display">
                    <span class="price">€${liveData.wholesale.price.toFixed(2)}</span>
                    <span class="unit">per MWh</span>
                </div>
                <div class="market-details">
                    <div>Load: ${(liveData.wholesale.load / 1000).toFixed(1)} GW</div>
                    <div>Renewable: ${liveData.wholesale.renewableShare.toFixed(1)}%</div>
                    <div>Imbalance: €${liveData.wholesale.imbalancePrice.toFixed(2)}/MWh</div>
                </div>
            </div>
            
            <!-- Energy Zero Consumer Status -->
            <div class="status-card energyzero">
                <h3>Energy Zero Consumer Pricing</h3>
                <div class="price-display">
                    <span class="price">€${liveData.consumer.electricityTotal.toFixed(2)}</span>
                    <span class="unit">per MWh</span>
                </div>
                <div class="price-breakdown">
                    <div>Energy: €${liveData.consumer.electricityEnergy.toFixed(2)}</div>
                    <div>Network: €${liveData.consumer.networkCosts.toFixed(2)}</div>
                    <div>Taxes: €${liveData.consumer.taxesAndFees.toFixed(2)}</div>
                </div>
                <div class="price-gap energyzero-gap">
                    Gap: +${liveData.consumer.priceGapPercentage.toFixed(1)}%
                </div>
                <div class="gas-price">
                    <small>Gas: €${liveData.consumer.gasPrice.toFixed(3)}/m³</small>
                </div>
            </div>
            
            <!-- Environmental Status -->
            <div class="status-card environmental">
                <h3>Environmental</h3>
                <div class="weather-display">
                    <div>${liveData.weather.temperature.toFixed(1)}°C</div>
                    <div>${liveData.weather.windSpeed.toFixed(1)} m/s wind</div>
                    <div>${liveData.weather.cloudCover.toFixed(0)}% clouds</div>
                </div>
                <div class="air-quality">
                    <div>AQI: ${liveData.airQuality.aqi.toFixed(0)}</div>
                    <div class="aqi-status">${this.getAQIStatus(liveData.airQuality.aqi)}</div>
                </div>
            </div>
        </div>
        `;
    }
    
    getAQIStatus(aqi) {
        if (aqi <= 50) return "Good";
        if (aqi <= 100) return "Moderate"; 
        if (aqi <= 150) return "Unhealthy for Sensitive";
        if (aqi <= 200) return "Unhealthy";
        return "Very Unhealthy";
    }
}
```

### Energy Zero Market Transparency Chart
```javascript
class EnergyZeroTransparencyChart {
    createPriceGapChart(rolling24hData) {
        const timestamps = rolling24hData.map(d => d.timestamp);
        const wholesalePrices = rolling24hData.map(d => d.wholesale_price);
        const energyZeroPrices = rolling24hData.map(d => d.consumer_price_total);
        const gasPrices = rolling24hData.map(d => d.gas_price * 100); // Scale for visibility
        const priceGaps = rolling24hData.map(d => d.price_gap);
        
        const traces = [
            {
                x: timestamps,
                y: wholesalePrices,
                type: 'scatter',
                mode: 'lines',
                name: 'Wholesale Price',
                line: { color: '#3b82f6', width: 3 }
            },
            {
                x: timestamps,
                y: energyZeroPrices,
                type: 'scatter',
                mode: 'lines',
                name: 'Energy Zero Consumer Price',
                line: { color: '#ef4444', width: 3 }
            },
            {
                x: timestamps,
                y: gasPrices,
                type: 'scatter',
                mode: 'lines',
                name: 'Energy Zero Gas Price (×100)',
                line: { color: '#10b981', width: 2, dash: 'dot' },
                yaxis: 'y2'
            },
            {
                x: timestamps,
                y: priceGaps,
                type: 'scatter',
                mode: 'lines',
                name: 'Price Gap',
                line: { color: '#f59e0b', width: 2, dash: 'dash' },
                yaxis: 'y2'
            }
        ];
        
        const layout = {
            title: 'Market Transparency: Wholesale vs Energy Zero Consumer Pricing',
            xaxis: { title: 'Time' },
            yaxis: { 
                title: 'Electricity Price (EUR/MWh)',
                side: 'left'
            },
            yaxis2: {
                title: 'Price Gap (EUR/MWh) | Gas Price (EUR/m³ ×100)', 
                side: 'right',
                overlaying: 'y'
            },
            legend: { orientation: 'h', y: 1.1 }
        };
        
        return { traces, layout };
    }
    
    createMarketEfficiencyChart(rolling24hData) {
        const timestamps = rolling24hData.map(d => d.timestamp);
        const priceGapPercentages = rolling24hData.map(d => d.price_gap_percentage);
        const taxBurdens = rolling24hData.map(d => d.tax_burden_percentage);
        
        const traces = [
            {
                x: timestamps,
                y: priceGapPercentages,
                type: 'scatter',
                mode: 'lines+markers',
                name: 'Energy Zero Price Gap %',
                line: { color: '#8b5cf6', width: 2 },
                marker: { size: 4 }
            },
            {
                x: timestamps,
                y: taxBurdens,
                type: 'scatter',
                mode: 'lines',
                name: 'Tax Burden %',
                line: { color: '#f97316', width: 2, dash: 'dash' }
            }
        ];
        
        const layout = {
            title: 'Energy Zero Market Efficiency Metrics',
            xaxis: { title: 'Time' },
            yaxis: { title: 'Percentage (%)' },
            legend: { orientation: 'h', y: 1.1 }
        };
        
        return { traces, layout };
    }
}
```

### Energy Zero Forecast Accuracy Dashboard
```javascript
class EnergyZeroAccuracyDashboard {
    createAccuracyMetrics(comparisonData) {
        const accuracyMetrics = this.calculateEnergyZeroAccuracyMetrics(comparisonData);
        
        return `
        <div class="accuracy-dashboard">
            <div class="accuracy-grid">
                <!-- Wholesale Forecast Accuracy -->
                <div class="accuracy-card">
                    <h4>Wholesale Price Forecast</h4>
                    <div class="accuracy-score ${this.getAccuracyClass(accuracyMetrics.wholesale.mape)}">
                        ${(100 - accuracyMetrics.wholesale.mape).toFixed(1)}%
                    </div>
                    <div class="accuracy-details">
                        <div>MAPE: ${accuracyMetrics.wholesale.mape.toFixed(1)}%</div>
                        <div>Avg Error: €${accuracyMetrics.wholesale.avgError.toFixed(2)}</div>
                        <div>Max Error: €${accuracyMetrics.wholesale.maxError.toFixed(2)}</div>
                    </div>
                </div>
                
                <!-- Energy Zero Consumer Forecast Accuracy -->
                <div class="accuracy-card energyzero-card">
                    <h4>Energy Zero Consumer Forecast</h4>
                    <div class="accuracy-score ${this.getAccuracyClass(accuracyMetrics.consumer.mape)}">
                        ${(100 - accuracyMetrics.consumer.mape).toFixed(1)}%
                    </div>
                    <div class="accuracy-details">
                        <div>MAPE: ${accuracyMetrics.consumer.mape.toFixed(1)}%</div>
                        <div>Avg Error: €${accuracyMetrics.consumer.avgError.toFixed(2)}</div>
                        <div>Price Gap Accuracy: ${accuracyMetrics.consumer.gapAccuracy.toFixed(1)}%</div>
                    </div>
                </div>
                
                <!-- Weather Forecast Accuracy -->
                <div class="accuracy-card">
                    <h4>Weather Forecast</h4>
                    <div class="accuracy-score ${this.getAccuracyClass(accuracyMetrics.weather.mape)}">
                        ${(100 - accuracyMetrics.weather.mape).toFixed(1)}%
                    </div>
                    <div class="accuracy-details">
                        <div>Temp MAPE: ${accuracyMetrics.weather.tempMape.toFixed(1)}%</div>
                        <div>Wind MAPE: ${accuracyMetrics.weather.windMape.toFixed(1)}%</div>
                    </div>
                </div>
                
                <!-- Energy Zero Market Transparency Score -->
                <div class="accuracy-card transparency-card">
                    <h4>Market Transparency (Energy Zero)</h4>
                    <div class="accuracy-score ${this.getTransparencyClass(accuracyMetrics.transparency.score)}">
                        ${accuracyMetrics.transparency.score.toFixed(0)}
                    </div>
                    <div class="accuracy-details">
                        <div>Avg Gap: ${accuracyMetrics.transparency.avgGap.toFixed(1)}%</div>
                        <div>Gap Volatility: ${accuracyMetrics.transparency.volatility.toFixed(1)}%</div>
                        <div>Tax Stability: ${accuracyMetrics.transparency.taxStability.toFixed(1)}%</div>
                    </div>
                </div>
            </div>
        </div>
        `;
    }
    
    calculateEnergyZeroAccuracyMetrics(comparisonData) {
        // Calculate MAPE for Energy Zero specific metrics
        const wholesaleErrors = comparisonData.map(d => d.wholesalePrice?.errorPercentage).filter(e => e !== undefined);
        const consumerErrors = comparisonData.map(d => d.consumerPrice?.errorPercentage).filter(e => e !== undefined);
        const weatherErrors = comparisonData.map(d => d.weather?.error).filter(e => e !== undefined);
        
        return {
            wholesale: {
                mape: this.calculateMAPE(wholesaleErrors),
                avgError: this.average(wholesaleErrors),
                maxError: Math.max(...wholesaleErrors)
            },
            consumer: {
                mape: this.calculateMAPE(consumerErrors),
                avgError: this.average(consumerErrors),
                gapAccuracy: this.calculateGapAccuracy(comparisonData)
            },
            weather: {
                mape: this.calculateMAPE(weatherErrors),
                tempMape: this.calculateMAPE(weatherErrors),
                windMape: this.calculateMAPE(weatherErrors)
            },
            transparency: {
                score: this.calculateEnergyZeroTransparencyScore(comparisonData),
                avgGap: this.calculateAverageGap(comparisonData),
                volatility: this.calculateGapVolatility(comparisonData),
                taxStability: this.calculateTaxStability(comparisonData)
            }
        };
    }
    
    calculateEnergyZeroTransparencyScore(comparisonData) {
        // Custom transparency score considering Energy Zero's pricing structure
        const gapVolatility = this.calculateGapVolatility(comparisonData);
        const taxStability = this.calculateTaxStability(comparisonData);
        const priceReactivity = this.calculatePriceReactivity(comparisonData);
        
        // Higher scores for stable gaps, stable taxes, and responsive pricing
        return Math.max(0, 100 - (gapVolatility * 2) - (100 - taxStability) - (100 - priceReactivity));
    }
}
```

### Real-Time Energy Zero Alerts
```javascript
class EnergyZeroAlerts {
    constructor() {
        this.alertThresholds = {
            priceDeviation: 15,          // % deviation from forecast
            energyZeroGapChange: 8,      // % change in Energy Zero gap
            gasElectricityCorrelation: 0.3, // Unusual gas-electricity correlation
            gridImbalance: 500,          // MW imbalance threshold
            aqiDegradation: 50           // AQI increase threshold
        };
        this.activeAlerts = new Set();
    }
    
    checkEnergyZeroAlerts(liveData, forecastData, previousData) {
        const alerts = [];
        
        // Energy Zero price deviation alert
        if (forecastData && liveData.consumer.electricityTotal) {
            const expectedConsumer = forecastData.price + 150; // Estimated markup
            const deviation = Math.abs(expectedConsumer - liveData.consumer.electricityTotal) / expectedConsumer * 100;
            if (deviation > this.alertThresholds.priceDeviation) {
                alerts.push({
                    type: 'energyzero_price_deviation',
                    severity: 'high',
                    message: `Energy Zero price deviating ${deviation.toFixed(1)}% from forecast`,
                    data: {
                        forecast: expectedConsumer,
                        actual: liveData.consumer.electricityTotal,
                        deviation: deviation
                    }
                });
            }
        }
        
        // Energy Zero gap change alert
        if (previousData && liveData.consumer.priceGapPercentage) {
            const gapChange = Math.abs(liveData.consumer.priceGapPercentage - previousData.consumer.priceGapPercentage);
            if (gapChange > this.alertThresholds.energyZeroGapChange) {
                alerts.push({
                    type: 'energyzero_gap_change',
                    severity: 'medium',
                    message: `Energy Zero price gap changed by ${gapChange.toFixed(1)}%`,
                    data: {
                        current: liveData.consumer.priceGapPercentage,
                        previous: previousData.consumer.priceGapPercentage,
                        change: gapChange
                    }
                });
            }
        }
        
        // Gas-electricity correlation alert
        if (liveData.consumer.gasPrice && liveData.consumer.electricityTotal) {
            const correlation = this.calculateGasElectricityCorrelation(liveData);
            if (Math.abs(correlation) > this.alertThresholds.gasElectricityCorrelation) {
                alerts.push({
                    type: 'gas_electricity_correlation',
                    severity: 'low',
                    message: `Unusual gas-electricity price correlation: ${(correlation * 100).toFixed(1)}%`,
                    data: {
                        gasPrice: liveData.consumer.gasPrice,
                        electricityPrice: liveData.consumer.electricityTotal,
                        correlation: correlation
                    }
                });
            }
        }
        
        return alerts;
    }
    
    displayEnergyZeroAlerts(alerts) {
        const alertContainer = document.getElementById('alerts-container');
        if (alerts.length === 0) {
            alertContainer.innerHTML = '<div class="no-alerts">No active Energy Zero alerts</div>';
            return;
        }
        
        alertContainer.innerHTML = alerts.map(alert => `
            <div class="alert alert-${alert.severity} ${alert.type.includes('energyzero') ? 'energyzero-alert' : ''}">
                <div class="alert-icon">${this.getAlertIcon(alert.type)}</div>
                <div class="alert-content">
                    <div class="alert-message">${alert.message}</div>
                    <div class="alert-time">${new Date().toLocaleTimeString()}</div>
                </div>
                <div class="alert-dismiss" onclick="this.parentElement.remove()">×</div>
            </div>
        `).join('');
    }
}
```

## Enhanced CSS for Energy Zero Integration

```css
/* Energy Zero specific styling */
.status-card.energyzero {
    border-left: 4px solid #10b981;
    background: linear-gradient(135deg, rgba(16, 185, 129, 0.1) 0%, rgba(16, 185, 129, 0.05) 100%);
}

.energyzero-gap {
    color: #10b981;
    font-weight: bold;
    font-size: 1.1rem;
}

.gas-price {
    margin-top: 10px;
    padding-top: 10px;
    border-top: 1px solid rgba(255, 255, 255, 0.1);
    color: #94a3b8;
}

.accuracy-card.energyzero-card {
    border: 2px solid #10b981;
    background: linear-gradient(135deg, rgba(16, 185, 129, 0.1) 0%, rgba(16, 185, 129, 0.05) 100%);
}

.accuracy-card.transparency-card {
    border: 2px solid #8b5cf6;
    background: linear-gradient(135deg, rgba(139, 92, 246, 0.1) 0%, rgba(139, 92, 246, 0.05) 100%);
}

.energyzero-alert {
    border-left: 4px solid #10b981;
}

.energyzero-alert .alert-icon::before {
    content: "⚡";
    color: #10b981;
}

/* Market transparency indicators */
.transparency-score.excellent { color: #10b981; }
.transparency-score.good { color: #3b82f6; }
.transparency-score.fair { color: #f59e0b; }
.transparency-score.poor { color: #ef4444; }

/* Gas price correlation indicators */
.gas-correlation-positive { color: #10b981; }
.gas-correlation-negative { color: #ef4444; }
.gas-correlation-neutral { color: #6b7280; }
```

## Performance Optimizations for Energy Zero

### Efficient Energy Zero Data Processing
```javascript
class EnergyZeroDataCache {
    constructor() {
        this.cache = new Map();
        this.cacheTimeout = 10 * 60 * 1000; // 10 minutes for Energy Zero data
    }
    
    processEnergyZeroDataEfficiently(rawData) {
        const cacheKey = this.generateEnergyZeroCacheKey(rawData);
        
        // Check cache first
        if (this.cache.has(cacheKey)) {
            const cached = this.cache.get(cacheKey);
            if (Date.now() - cached.timestamp < this.cacheTimeout) {
                return cached.data;
            }
        }
        
        // Process Energy Zero data
        const processedData = this.performEnergyZeroProcessing(rawData);
        
        // Cache result
        this.cache.set(cacheKey, {
            data: processedData,
            timestamp: Date.now()
        });
        
        return processedData;
    }
    
    performEnergyZeroProcessing(rawData) {
        // Process Energy Zero specific data transformations
        const processed = {
            currentHourPricing: this.extractCurrentHourPricing(rawData),
            dailyPricePattern: this.analyzeDailyPattern(rawData),
            gasElectricityCorrelation: this.calculateGasElectricityCorrelation(rawData),
            priceTransmissionMetrics: this.calculateTransmissionMetrics(rawData)
        };
        
        return processed;
    }
    
    // Clean up old cache entries
    cleanEnergyZeroCache() {
        const now = Date.now();
        for (const [key, value] of this.cache.entries()) {
            if (now - value.timestamp > this.cacheTimeout) {
                this.cache.delete(key);
            }
        }
    }
}
```

## Auto-Refresh Implementation for Energy Zero

### Energy Zero Aware Refresh Manager
```javascript
class EnergyZeroRefreshManager {
    constructor(dashboard) {
        this.dashboard = dashboard;
        this.refreshInterval = 15 * 60 * 1000; // 15 minutes
        this.energyZeroUpdateInterval = 60 * 60 * 1000; // 1 hour for Energy Zero pricing
        this.refreshTimer = null;
        this.energyZeroTimer = null;
        this.isRefreshing = false;
    }
    
    start() {
        // Standard data refresh every 15 minutes
        this.refreshTimer = setInterval(() => {
            this.refreshData();
        }, this.refreshInterval);
        
        // Energy Zero specific refresh at hour boundaries
        this.scheduleEnergyZeroRefresh();
        
        // Initial refresh
        this.refreshData();
    }
    
    scheduleEnergyZeroRefresh() {
        // Calculate milliseconds until next hour
        const now = new Date();
        const nextHour = new Date(now.getFullYear(), now.getMonth(), now.getDate(), now.getHours() + 1, 0, 0, 0);
        const timeUntilNextHour = nextHour.getTime() - now.getTime();
        
        // Schedule refresh at next hour boundary
        setTimeout(() => {
            this.refreshEnergyZeroData();
            
            // Then refresh every hour
            this.energyZeroTimer = setInterval(() => {
                this.refreshEnergyZeroData();
            }, this.energyZeroUpdateInterval);
        }, timeUntilNextHour);
    }
    
    async refreshEnergyZeroData() {
        console.log('Refreshing Energy Zero data at hour boundary...');
        
        try {
            const energyZeroData = await this.dashboard.loadEnergyZeroData();
            this.dashboard.updateEnergyZeroComponents(energyZeroData);
            this.showEnergyZeroUpdateNotification();
        } catch (error) {
            console.error('Energy Zero data refresh failed:', error);
        }
    }
    
    async refreshData() {
        if (this.isRefreshing) return;
        
        this.isRefreshing = true;
        this.showRefreshIndicator();
        
        try {
            const newData = await this.dashboard.loadAllData();
            this.dashboard.updateAllComponents(newData);
            this.updateRefreshTimestamp();
            
            // Check if Energy Zero data has been updated
            this.checkEnergyZeroDataFreshness(newData);
        } catch (error) {
            console.error('Data refresh failed:', error);
            this.showRefreshError();
        } finally {
            this.isRefreshing = false;
            this.hideRefreshIndicator();
        }
    }
    
    checkEnergyZeroDataFreshness(data) {
        if (data.liveData && data.liveData.consumer_price_total) {
            const dataTimestamp = new Date(data.liveData.timestamp);
            const currentHour = new Date();
            currentHour.setMinutes(0, 0, 0);
            
            if (dataTimestamp >= currentHour) {
                this.showEnergyZeroFreshDataIndicator();
            }
        }
    }
    
    showEnergyZeroUpdateNotification() {
        const notification = document.createElement('div');
        notification.className = 'energyzero-update-notification';
        notification.innerHTML = `
            <div class="notification-content">
                <span class="energyzero-icon">⚡</span>
                <span>Energy Zero prices updated for current hour</span>
            </div>
        `;
        
        document.body.appendChild(notification);
        
        // Auto-remove after 5 seconds
        setTimeout(() => {
            notification.remove();
        }, 5000);
    }
    
    stop() {
        if (this.refreshTimer) {
            clearInterval(this.refreshTimer);
            this.refreshTimer = null;
        }
        if (this.energyZeroTimer) {
            clearInterval(this.energyZeroTimer);
            this.energyZeroTimer = null;
        }
    }
}
```

## Enhanced Main Layout for Energy Zero

### Complete Dashboard Layout
```html
<!-- Enhanced Augur layout with Energy Zero integration -->
<div class="enhanced-dashboard">
    <header class="dashboard-header">
        <h1>Energy Market Dashboard</h1>
        <div class="data-status">
            <span id="forecast-status">Forecasts: <span class="status-ok">OK</span></span>
            <span id="live-status">Live Data: <span class="status-ok">OK</span></span>
            <span id="energyzero-status">Energy Zero: <span class="status-ok">OK</span></span>
            <span id="last-update">Updated: <span id="update-time">--:--</span></span>
        </div>
    </header>
    
    <!-- Real-time alerts banner -->
    <div id="alerts-container" class="alerts-banner"></div>
    
    <!-- Energy Zero price summary banner -->
    <div class="energyzero-summary-banner">
        <div class="energyzero-current-price">
            <span class="label">Current Energy Zero Price:</span>
            <span id="energyzero-current-price" class="price">€---.--</span>
            <span class="unit">per MWh</span>
        </div>
        <div class="energyzero-gap">
            <span class="label">vs Wholesale:</span>
            <span id="energyzero-gap" class="gap">+---%</span>
        </div>
        <div class="energyzero-gas">
            <span class="label">Gas:</span>
            <span id="energyzero-gas-price" class="gas-price">€-.---</span>
            <span class="unit">per m³</span>
        </div>
    </div>
    
    <!-- Live status panels -->
    <section class="live-status-section">
        <div id="live-status-panels"></div>
    </section>
    
    <!-- Main chart area -->
    <section class="charts-section">
        <div class="chart-tabs">
            <button class="tab-btn active" data-tab="forecast-actual">Forecast vs Actual</button>
            <button class="tab-btn" data-tab="energyzero-transparency">Energy Zero Transparency</button>
            <button class="tab-btn" data-tab="market-efficiency">Market Efficiency</button>
            <button class="tab-btn" data-tab="environmental">Environmental Impact</button>
        </div>
        <div id="main-chart-container"></div>
    </section>
    
    <!-- Analytics dashboard -->
    <section class="analytics-section">
        <div class="analytics-grid">
            <div id="accuracy-metrics"></div>
            <div id="energyzero-metrics"></div>
            <div id="correlation-analysis"></div>
        </div>
    </section>
    
    <!-- Controls -->
    <section class="controls-section">
        <div class="control-group">
            <label for="time-range">Time Range:</label>
            <select id="time-range">
                <option value="1h">Last Hour</option>
                <option value="6h">Last 6 Hours</option>
                <option value="24h" selected>Last 24 Hours</option>
                <option value="48h">Last 48 Hours</option>
            </select>
        </div>
        <div class="control-group">
            <label for="price-threshold">Price Alert Threshold:</label>
            <input type="number" id="price-threshold" value="50" step="5" min="0" max="200">
            <span>EUR/MWh</span>
        </div>
        <div class="control-group">
            <label for="energyzero-alerts">Energy Zero Alerts:</label>
            <input type="checkbox" id="energyzero-alerts" checked>
            <span>Enable price gap alerts</span>
        </div>
        <div class="control-group">
            <label for="auto-refresh">Auto Refresh:</label>
            <input type="checkbox" id="auto-refresh" checked>
            <span>Every 15 minutes</span>
        </div>
    </section>
    
    <!-- Energy Zero specific controls -->
    <section class="energyzero-controls-section">
        <h3>Energy Zero Analysis</h3>
        <div class="control-group">
            <label for="show-gas-correlation">Show Gas Correlation:</label>
            <input type="checkbox" id="show-gas-correlation">
        </div>
        <div class="control-group">
            <label for="transparency-threshold">Transparency Threshold:</label>
            <input type="range" id="transparency-threshold" min="60" max="95" value="80">
            <span id="transparency-value">80</span>%
        </div>
        <div class="control-group">
            <button id="export-energyzero-data" class="export-btn">Export Energy Zero Data</button>
        </div>
    </section>
</div>
```

## Energy Zero Data Export Functionality

### Export Implementation
```javascript
class EnergyZeroDataExporter {
    constructor() {
        this.exportFormats = ['csv', 'json', 'xlsx'];
    }
    
    async exportEnergyZeroData(format = 'csv', timeRange = '24h') {
        try {
            const data = await this.loadEnergyZeroDataForExport(timeRange);
            const exportData = this.formatEnergyZeroDataForExport(data);
            
            switch (format) {
                case 'csv':
                    this.downloadCSV(exportData);
                    break;
                case 'json':
                    this.downloadJSON(exportData);
                    break;
                case 'xlsx':
                    this.downloadXLSX(exportData);
                    break;
            }
        } catch (error) {
            console.error('Energy Zero data export failed:', error);
            this.showExportError(error);
        }
    }
    
    formatEnergyZeroDataForExport(data) {
        return data.map(snapshot => ({
            timestamp: snapshot.timestamp,
            wholesale_price: snapshot.wholesale_price,
            energyzero_electricity_total: snapshot.consumer_price_total,
            energyzero_electricity_energy: snapshot.consumer_price_energy,
            energyzero_gas_price: snapshot.gas_price,
            network_costs: snapshot.network_costs,
            taxes_and_fees: snapshot.taxes_and_fees,
            price_gap_eur: snapshot.price_gap,
            price_gap_percentage: snapshot.price_gap_percentage,
            tax_burden_percentage: snapshot.tax_burden_percentage,
            weather_temperature: snapshot.temperature,
            weather_wind_speed: snapshot.wind_speed,
            renewable_share: snapshot.renewable_share,
            air_quality_aqi: snapshot.aqi
        }));
    }
    
    downloadCSV(data) {
        const headers = Object.keys(data[0]).join(',');
        const rows = data.map(row => Object.values(row).join(','));
        const csvContent = [headers, ...rows].join('\n');
        
        const blob = new Blob([csvContent], { type: 'text/csv' });
        const url = URL.createObjectURL(blob);
        
        const link = document.createElement('a');
        link.href = url;
        link.download = `energyzero_data_${new Date().toISOString().split('T')[0]}.csv`;
        link.click();
        
        URL.revokeObjectURL(url);
    }
}
```

## Additional CSS for Energy Zero Features

```css
/* Energy Zero summary banner */
.energyzero-summary-banner {
    display: flex;
    justify-content: space-around;
    align-items: center;
    background: linear-gradient(135deg, rgba(16, 185, 129, 0.1) 0%, rgba(16, 185, 129, 0.05) 100%);
    border: 1px solid rgba(16, 185, 129, 0.2);
    border-radius: 12px;
    padding: 15px;
    margin-bottom: 20px;
}

.energyzero-summary-banner .label {
    color: #94a3b8;
    font-size: 0.9rem;
    margin-right: 8px;
}

.energyzero-summary-banner .price {
    color: #10b981;
    font-size: 1.4rem;
    font-weight: bold;
}

.energyzero-summary-banner .gap {
    color: #f59e0b;
    font-size: 1.2rem;
    font-weight: bold;
}

.energyzero-summary-banner .gas-price {
    color: #3b82f6;
    font-size: 1.2rem;
    font-weight: bold;
}

/* Energy Zero controls section */
.energyzero-controls-section {
    background: rgba(16, 185, 129, 0.05);
    border: 1px solid rgba(16, 185, 129, 0.1);
    border-radius: 12px;
    padding: 20px;
    margin-top: 20px;
}

.energyzero-controls-section h3 {
    color: #10b981;
    margin-bottom: 15px;
}

/* Energy Zero update notification */
.energyzero-update-notification {
    position: fixed;
    top: 20px;
    right: 20px;
    background: linear-gradient(135deg, #10b981 0%, #059669 100%);
    color: white;
    padding: 12px 20px;
    border-radius: 8px;
    box-shadow: 0 4px 12px rgba(16, 185, 129, 0.3);
    z-index: 1000;
    animation: slideInRight 0.3s ease-out;
}

.energyzero-update-notification .energyzero-icon {
    margin-right: 8px;
    font-size: 1.2rem;
}

@keyframes slideInRight {
    from {
        transform: translateX(100%);
        opacity: 0;
    }
    to {
        transform: translateX(0);
        opacity: 1;
    }
}

/* Export button styling */
.export-btn {
    background: linear-gradient(135deg, #10b981 0%, #059669 100%);
    color: white;
    border: none;
    padding: 10px 20px;
    border-radius: 6px;
    cursor: pointer;
    font-weight: 500;
    transition: all 0.2s ease;
}

.export-btn:hover {
    background: linear-gradient(135deg, #059669 0%, #047857 100%);
    transform: translateY(-1px);
    box-shadow: 0 4px 12px rgba(16, 185, 129, 0.3);
}
```

---

*This comprehensive dashboard integration guide provides detailed instructions for enhancing Augur with Energy Zero consumer pricing data, creating a powerful platform for market transparency analysis, forecast validation, and real-time energy market monitoring with authentic Dutch consumer pricing insights.*
        
```


# docs\energylivedata_overview.md
```markdown
# energyLiveData - Project Overview

## Executive Summary

**energyLiveData** is a real-time energy data collection system designed to complement the existing **energydatahub** (day-ahead forecasts) and **Augur** (visualization) projects. The system collects actual energy market data, weather conditions, and environmental metrics at 15-minute intervals, enabling comprehensive forecast validation, market transparency analysis, and real-time monitoring using **Energy Zero** as the consumer pricing data source.

## Project Context & Architecture

### Existing Ecosystem
```
energydatahub (Day-ahead Forecasts)
    ↓ Daily updates
Augur (Visualization)
    ↓ User interface
Academic Research & Energy Optimization
```

### Enhanced Ecosystem with energyLiveData
```
┌─────────────────┐    ┌─────────────────┐
│ energydatahub   │    │ energyLiveData  │
│ (Forecasts)     │    │ (Real-time)     │
│ • Energy fcst   │    │ • Energy actual │
│ • Weather fcst  │    │ • Weather live  │
│ • Solar fcst    │    │ • Energy Zero   │
│ • Air quality   │    │ • Grid status   │
└─────────────────┘    └─────────────────┘
         │                       │
         └──────────┬────────────┘
                    ▼
        ┌───────────────────────┐
        │ Augur   │
        │                       │
        │ • Forecast validation │
        │ • Market transparency │
        │ • Real-time monitoring│
        │ • Research analytics  │
        └───────────────────────┘
```

## Core Objectives

### Primary Goals
1. **Forecast Validation**: Compare energydatahub predictions with actual market outcomes
2. **Market Transparency**: Analyze wholesale vs consumer pricing relationships via Energy Zero
3. **Real-time Monitoring**: Provide current energy market and grid status
4. **Academic Research**: Enable studies in energy market behavior and transparency

### Key Value Propositions
- **Complete Market View**: Wholesale + Energy Zero consumer data + environmental data
- **Research Platform**: Unique dataset for academic publications on Dutch energy market
- **Market Analysis**: Price transmission and transparency studies using real consumer pricing
- **Grid Intelligence**: Real-time balancing and renewable integration insights

## Data Sources & Coverage

### Energy Market Data
- **Wholesale**: ENTSO-E actual prices, TenneT grid data
- **Consumer**: Energy Zero dynamic pricing (electricity + gas)
- **Grid**: Imbalance prices, system status, cross-border flows

### Energy Zero Integration Benefits
- **No Authentication Required**: Simplified setup compared to other consumer APIs
- **Real-time Pricing**: Current hour electricity and gas prices
- **Forecast Data**: Tomorrow's prices when available (typically published around 15:00)
- **Comprehensive Coverage**: Includes tax breakdowns and total consumer costs
- **High Reliability**: Well-maintained Dutch energy data source

### Environmental Data  
- **Weather**: Real-time conditions, wind/solar generation correlation
- **Air Quality**: Live measurements from Dutch monitoring network

### Update Frequency
- **Collection**: Every 15 minutes
- **Storage**: Rolling 24-48 hour window
- **Integration**: Automatic Augur updates

## Technical Architecture

### Collection System
- **Platform**: GitHub Actions (15-minute cron)
- **Languages**: Python 3.11+ with python-energyzero library
- **Security**: AES-CBC encryption + HMAC-SHA256
- **Storage**: GitHub Pages with rolling data management

### Integration Points
- **Data Hub Integration**: Automatic comparison with energydatahub forecasts
- **Dashboard Integration**: Real-time data feeds and analysis
- **API Integration**: Energy Zero + multiple simultaneous data source collection

### Data Flow
```
ENTSO-E → TenneT → Energy Zero → Weather APIs → energyLiveData Collector → 
Processing & Validation → Encryption → GitHub Pages → Augur → User Interface
```

## Key Features & Capabilities

### Market Analysis with Energy Zero
- **Price Gap Analysis**: Wholesale vs Energy Zero consumer pricing differences
- **Transmission Speed**: How quickly wholesale changes reach Energy Zero customers
- **Tax Burden Tracking**: Component breakdown of Energy Zero consumer pricing
- **Market Efficiency**: Price signal transmission analysis in Dutch retail market
- **Gas-Electricity Correlation**: Cross-commodity pricing analysis via Energy Zero

### Forecast Validation
- **Accuracy Metrics**: MAPE, correlation analysis across domains
- **Consumer Price Validation**: energydatahub forecasts vs Energy Zero actuals
- **Pattern Recognition**: When and why forecasts deviate from Energy Zero reality
- **Cross-domain Analysis**: Weather impact on Energy Zero pricing accuracy
- **Model Improvement**: Data for enhancing forecast algorithms

### Real-time Intelligence
- **Grid Status**: Current load, imbalance, renewable share
- **Price Alerts**: Significant deviations from forecasts vs Energy Zero actuals
- **Weather Correlation**: Live weather impact on Energy Zero pricing
- **Environmental Tracking**: Air quality and renewable generation correlation

## Academic & Research Value

### Research Opportunities Enhanced by Energy Zero
1. **Energy Market Transparency**: Dutch energy pricing chain analysis using real consumer data
2. **Forecast Accuracy Studies**: Multi-domain prediction validation with Energy Zero baseline
3. **Consumer Behavior**: Response to dynamic pricing signals in Energy Zero customer base
4. **Weather-Energy Correlations**: Real-time impact analysis on consumer pricing
5. **Grid Balancing**: Renewable integration effects on retail pricing

### Publication Potential
- **Market Transparency**: Policy-relevant pricing analysis using Energy Zero as consumer benchmark
- **Forecast Validation**: Methodology and accuracy studies with real consumer pricing data
- **Consumer Economics**: Dynamic pricing effectiveness in Dutch retail market
- **Grid Operations**: Real-time balancing impact on consumer pricing via Energy Zero

## Implementation Strategy

### Phased Development
```
Phase 1: Core Collection (Weeks 1-2)
├── ENTSO-E actual data integration
├── Energy Zero consumer pricing setup
├── Basic weather integration
└── Initial dashboard integration

Phase 2: Complete Integration (Weeks 3-4)  
├── All data sources operational
├── Energy Zero gas pricing integration
├── Comprehensive market analysis
├── Advanced dashboard features
└── Academic research framework

Phase 3: Research & Enhancement (Ongoing)
├── Publication preparation with Energy Zero insights
├── Community engagement
├── Feature enhancement
└── Commercial evaluation
```

### Success Metrics
- **Technical**: >95% data availability, <30min latency, Energy Zero API reliability >98%
- **Academic**: Research publications featuring Energy Zero market analysis
- **Functional**: Forecast accuracy vs Energy Zero actuals, market insights
- **Impact**: Policy relevance, tool adoption by energy sector

## Resource Requirements

### Development
- **Time**: 6-8 weeks initial implementation (reduced due to Energy Zero simplicity)
- **Skills**: Python, API integration, data analysis, Energy Zero API familiarity
- **Infrastructure**: GitHub Actions, minimal cloud services

### Operational
- **Cost**: €0-3/month (Energy Zero is free, other APIs minimal cost)
- **Maintenance**: 3-4 hours/month (reduced due to Energy Zero reliability)
- **Monitoring**: Automated with alert systems

### Academic
- **Research Time**: 8+ hours/month for Energy Zero market analysis
- **Publication Support**: Data visualization, statistical analysis of consumer pricing
- **Community Engagement**: Documentation, presentations on Dutch market transparency

## Risk Assessment

### Technical Risks (Low)
- Energy Zero API reliability → Excellent track record, fallback caching
- API rate limiting → Energy Zero has generous limits, staggered requests for other APIs
- Data inconsistency → Cross-validation with Energy Zero as consumer pricing baseline
- Integration complexity → Energy Zero simplifies consumer data collection

### Operational Risks (Low)
- Service downtime → Graceful degradation, Energy Zero caching
- Format changes → Energy Zero library handles API changes automatically
- Storage limitations → Rolling windows, compression

### Academic Risks (Low)
- Data quality → Energy Zero provides high-quality consumer pricing validation
- Research relevance → Strong policy relevance due to Energy Zero market position
- Publication timeline → Iterative approach, multiple studies possible
```


# docs\energylivedata_research.md
```markdown
# energyLiveData - Research & Analytics Framework

## Research Overview

The **energyLiveData** system creates unique opportunities for academic research in energy markets, forecast validation, and market transparency. This framework outlines research methodologies, potential studies, and analytical approaches enabled by the comprehensive real-time energy data platform.

## Research Domains

### 1. Energy Market Transparency
**Focus**: Analyzing price transmission from wholesale to consumer markets

#### Key Research Questions
- How efficiently do wholesale price changes transmit to consumer pricing?
- What factors influence price transmission speed and completeness?
- How do regulatory changes affect market transparency?
- What role do taxes and network costs play in price volatility?

#### Methodology
```python
class PriceTransmissionAnalysis:
    def __init__(self, data_window_days=30):
        self.data_window = data_window_days
        
    def analyze_transmission_efficiency(self, wholesale_data, consumer_data):
        """Analyze speed and completeness of price transmission"""
        # Vector Error Correction Model (VECM)
        # Cross-correlation analysis with time lags
        # Impulse response functions
        
    def calculate_transmission_metrics(self):
        return {
            'transmission_speed': self.calculate_lag_time(),
            'transmission_completeness': self.calculate_pass_through_rate(),
            'price_elasticity': self.calculate_elasticity(),
            'volatility_transmission': self.analyze_volatility_spillover()
        }
```

#### Expected Outcomes
- **Academic Papers**: "Price Transmission in Dutch Energy Markets: A Real-Time Analysis"
- **Policy Impact**: Recommendations for energy market regulation
- **Industry Value**: Insights for energy retailers and consumer advocates

### 2. Forecast Accuracy & Validation
**Focus**: Multi-domain forecast performance analysis

#### Research Questions
- Which forecasting models perform best under different market conditions?
- How do weather forecasts impact energy price prediction accuracy?
- What are the key factors causing forecast deviations?
- How can real-time data improve forecasting models?

#### Analytical Framework
```python
class ForecastValidationFramework:
    def __init__(self):
        self.accuracy_metrics = {
            'MAPE': self.mean_absolute_percentage_error,
            'RMSE': self.root_mean_square_error,
            'MAE': self.mean_absolute_error,
            'Directional_Accuracy': self.directional_accuracy,
            'Peak_Accuracy': self.peak_prediction_accuracy
        }
        
    def comprehensive_accuracy_analysis(self, forecasts, actuals):
        """Multi-dimensional accuracy analysis"""
        results = {}
        
        # Time-based accuracy patterns
        results['hourly_patterns'] = self.analyze_hourly_accuracy(forecasts, actuals)
        results['seasonal_patterns'] = self.analyze_seasonal_accuracy(forecasts, actuals)
        results['weather_dependency'] = self.analyze_weather_correlation(forecasts, actuals)
        
        # Market condition analysis
        results['volatile_periods'] = self.analyze_volatile_period_accuracy(forecasts, actuals)
        results['extreme_events'] = self.analyze_extreme_event_prediction(forecasts, actuals)
        
        return results
        
    def machine_learning_improvement(self, historical_data):
        """Develop improved forecasting models"""
        # Feature engineering with real-time data
        # Ensemble methods combining multiple forecast sources
        # Deep learning models with attention mechanisms
        # Real-time model updating and adaptation
```

#### Research Output Targets
- **Methodology Papers**: Novel forecast validation techniques
- **Performance Studies**: Comparative analysis of forecasting models
- **Improvement Algorithms**: ML-enhanced forecasting methods

### 3. Weather-Energy Correlations
**Focus**: Real-time impact of weather on energy markets

#### Research Scope
- Renewable energy generation vs weather correlation accuracy
- Weather-driven price volatility patterns
- Extreme weather event impact on energy markets
- Seasonal vs daily weather influence on pricing

#### Analysis Methodology
```python
class WeatherEnergyCorrelationAnalysis:
    def __init__(self):
        self.weather_variables = [
            'temperature', 'wind_speed', 'solar_irradiance', 
            'cloud_cover', 'precipitation', 'atmospheric_pressure'
        ]
        self.energy_variables = [
            'wholesale_price', 'renewable_share', 'total_load',
            'imbalance_price', 'cross_border_flow'
        ]
        
    def real_time_correlation_analysis(self, weather_data, energy_data):
        """Analyze real-time weather-energy relationships"""
        correlations = {}
        
        # Direct correlations
        for weather_var in self.weather_variables:
            for energy_var in self.energy_variables:
                correlations[f"{weather_var}_{energy_var}"] = self.calculate_correlation(
                    weather_data[weather_var], energy_data[energy_var]
                )
        
        # Lagged correlations (weather predicting energy)
        lag_correlations = self.analyze_lagged_correlations(weather_data, energy_data)
        
        # Non-linear relationships
        non_linear = self.analyze_non_linear_relationships(weather_data, energy_data)
        
        return {
            'direct_correlations': correlations,
            'la
```


# docs\energylivedata_technical.md
```markdown
# energyLiveData - Technical Implementation Guide

## System Architecture

### Component Overview
```
┌─────────────────────────────────────────────────────────────┐
│                    energyLiveData System                    │
├─────────────────────────────────────────────────────────────┤
│  Data Collection Layer                                      │
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────────────────┐│
│  │ Energy APIs │ │ Weather APIs│ │ Environmental APIs      ││
│  │ • ENTSO-E   │ │ • OpenWeath │ │ • Luchtmeetnet         ││
│  │ • TenneT    │ │ • MeteoSrvr │ │ • Air Quality          ││
│  │ • EnergyZero│ │ • Solar     │ │ • Grid Monitoring      ││
│  └─────────────┘ └─────────────┘ └─────────────────────────┘│
├─────────────────────────────────────────────────────────────┤
│  Processing Layer                                           │
│  ┌─────────────────────────────────────────────────────────┐│
│  │ • Data Validation & Quality Control                     ││
│  │ • Multi-source Integration & Correlation               ││
│  │ • Market Analysis (Price Gaps, Transmission)           ││
│  │ • Rolling Window Management                             ││
│  │ • Forecast Comparison Engine                            ││
│  └─────────────────────────────────────────────────────────┘│
├─────────────────────────────────────────────────────────────┤
│  Storage Layer                                              │
│  ┌─────────────────────────────────────────────────────────┐│
│  │ • Encrypted JSON Storage (GitHub Pages)                ││
│  │ • Rolling 24-48h Data Windows                           ││
│  │ • Market Analysis Results                               ││
│  │ • Quality Metrics & Monitoring Data                     ││
│  └─────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────┘
```

## Data Sources & API Integration

### Energy Market APIs

#### ENTSO-E Transparency Platform
```python
# Actual energy market data
ENTSOE_ENDPOINTS = {
    'actual_load': {
        'documentType': 'A65',
        'processType': 'A16',
        'area': '10YNL----------L'
    },
    'actual_generation': {
        'documentType': 'A75',
        'processType': 'A16', 
        'area': '10YNL----------L'
    },
    'actual_prices': {
        'documentType': 'A44',
        'area': '10YNL----------L'
    }
}
```

#### TenneT TSO Data
```python
# Grid balancing and imbalance data
TENNET_ENDPOINTS = {
    'imbalance_prices': 'https://www.tennet.org/english/operational_management/export_data.aspx',
    'system_imbalance': 'https://www.tennet.org/english/operational_management/export_data.aspx',
    'cross_border_flows': 'https://www.tennet.org/english/operational_management/export_data.aspx'
}
```

#### Energy Zero Consumer API
```python
# Energy Zero pricing integration
from energyzero import EnergyZero

class EnergyZeroCollector:
    def __init__(self):
        self.energyzero = EnergyZero()
        
    async def collect_consumer_data(self):
        """Collect current and forecast pricing data from Energy Zero"""
        today = datetime.now().date()
        tomorrow = today + timedelta(days=1)
        
        try:
            # Get current energy prices
            current_gas_price = await self.energyzero.gas_prices(today, today)
            current_energy_prices = await self.energyzero.energy_prices(today, today)
            
            # Get tomorrow's prices if available
            tomorrow_energy_prices = None
            try:
                tomorrow_energy_prices = await self.energyzero.energy_prices(tomorrow, tomorrow)
            except Exception:
                # Tomorrow's prices might not be available yet
                pass
                
            return {
                'current_energy_prices': current_energy_prices,
                'current_gas_prices': current_gas_price,
                'tomorrow_energy_prices': tomorrow_energy_prices,
                'collection_timestamp': datetime.now(timezone.utc)
            }
        except Exception as e:
            logger.error(f"Energy Zero collection failed: {e}")
            return None
            
    def extract_current_pricing(self, energy_zero_data):
        """Extract current hour pricing from Energy Zero data"""
        if not energy_zero_data or not energy_zero_data.get('current_energy_prices'):
            return None
            
        current_hour = datetime.now().replace(minute=0, second=0, microsecond=0)
        
        # Find current hour price in Energy Zero data
        for price_point in energy_zero_data['current_energy_prices']:
            if price_point.datetime.replace(tzinfo=None) == current_hour:
                return {
                    'consumer_price_total': price_point.price_incl_tax * 1000,  # Convert €/kWh to €/MWh
                    'consumer_price_energy': price_point.price_excl_tax * 1000,  # Convert €/kWh to €/MWh
                    'timestamp': price_point.datetime,
                    'source': 'energyzero'
                }
        
        return None
```

### Environmental APIs

#### Weather Data Sources
```python
WEATHER_APIS = {
    'openweather': {
        'current': 'https://api.openweathermap.org/data/2.5/weather',
        'forecast': 'https://api.openweathermap.org/data/2.5/forecast'
    },
    'meteoserver': {
        'current': 'https://data.meteoserver.nl/api/actueel.php',
        'forecast': 'https://data.meteoserver.nl/api/uurverwachting.php'
    }
}
```

#### Air Quality Integration
```python
AIR_QUALITY_CONFIG = {
    'luchtmeetnet': {
        'stations': 'https://api.luchtmeetnet.nl/open_api/stations',
        'measurements': 'https://api.luchtmeetnet.nl/open_api/measurements'
    }
}
```

## Data Models & Structures

### Core Data Model
```python
@dataclass
class LiveEnergySnapshot:
    timestamp: datetime
    
    # Wholesale Market Data
    wholesale_price: float          # EUR/MWh (ENTSO-E)
    actual_load: float              # MW
    renewable_share: float          # %
    imbalance_price: float          # EUR/MWh (TenneT)
    system_imbalance: float         # MW
    cross_border_flow: float        # MW
    
    # Consumer Market Data (Energy Zero)
    consumer_price_total: float     # EUR/MWh (including all taxes)
    consumer_price_energy: float    # EUR/MWh (energy component only)
    gas_price: float               # EUR/m³ (Energy Zero gas pricing)
    
    # Derived Consumer Metrics
    network_costs: float            # EUR/MWh (estimated from price difference)
    taxes_and_fees: float          # EUR/MWh (estimated from price difference)
    
    # Weather Data
    temperature: float              # °C
    wind_speed: float              # m/s
    wind_direction: float          # degrees
    solar_irradiance: float        # W/m²
    cloud_cover: float             # %
    precipitation: float           # mm/h
    
    # Air Quality Data
    aqi: float                     # Air Quality Index
    pm25: float                    # μg/m³
    pm10: float                    # μg/m³
    no2: float                     # μg/m³
    o3: float                      # μg/m³
    
    # Calculated Metrics
    price_gap: float               # Consumer - Wholesale
    price_gap_percentage: float    # (Consumer/Wholesale - 1) * 100
    tax_burden_percentage: float   # Taxes/Total * 100
    
    # Quality Indicators
    data_quality: Dict[str, float] # Quality score per source
    source_availability: Dict[str, bool]
    collection_timestamp: datetime
    
    def validate_data(self) -> bool:
        """Validate data integrity and ranges"""
        
    def calculate_derived_metrics(self):
        """Calculate price gaps and correlations from Energy Zero data"""
        if self.consumer_price_total and self.consumer_price_energy:
            # Calculate derived costs from Energy Zero pricing structure
            self.taxes_and_fees = self.consumer_price_total - self.consumer_price_energy
            self.network_costs = self.taxes_and_fees * 0.6  # Estimated network portion
            self.taxes_and_fees = self.taxes_and_fees * 0.4  # Estimated tax portion
            
        if self.wholesale_price and self.consumer_price_total:
            self.price_gap = self.consumer_price_total - self.wholesale_price
            self.price_gap_percentage = (self.consumer_price_total / self.wholesale_price - 1) * 100
            
        if self.consumer_price_total and self.taxes_and_fees:
            self.tax_burden_percentage = (self.taxes_and_fees / self.consumer_price_total) * 100
        
    def to_dict(self) -> dict:
        """Convert to JSON-serializable format"""
```

### Market Analysis Models
```python
@dataclass
class MarketAnalysis:
    analysis_timestamp: datetime
    analysis_period_hours: int
    
    # Price Transmission Analysis
    price_transmission_speed: float    # Hours for wholesale→consumer
    transmission_efficiency: float     # % of wholesale change reflected
    price_volatility_wholesale: float  # Standard deviation
    price_volatility_consumer: float   # Standard deviation
    
    # Energy Zero Market Structure Analysis
    average_price_gap: float           # Mean wholesale→consumer gap
    tax_burden_trend: float           # Change in tax percentage
    network_cost_trend: float        # Change in network costs
    gas_price_correlation: float      # Gas vs electricity price correlation
    
    # Forecast Validation
    wholesale_forecast_mape: float    # Mean Absolute Percentage Error
    consumer_forecast_mape: float     # MAPE for consumer prices
    weather_forecast_mape: float      # Weather prediction accuracy
    
    # Correlation Analysis
    weather_price_correlation: float  # Weather→price correlation
    load_price_correlation: float     # Load→price correlation
    renewable_price_correlation: float # Renewable→price correlation
```

## Collection Architecture

### GitHub Actions Workflow
```yaml
name: energyLiveData Collection

on:
  schedule:
    - cron: '*/15 * * * *'  # Every 15 minutes
    - cron: '0 */6 * * *'   # Every 6 hours (cleanup)
  workflow_dispatch:

jobs:
  collect-live-data:
    runs-on: ubuntu-latest
    timeout-minutes: 10
    
    steps:
    - name: Checkout repository
      uses: actions/checkout@v4
      
    - name: Set up Python
      uses: actions/setup-python@v4
      with:
        python-version: '3.11'
        
    - name: Install dependencies
      run: |
        pip install -r requirements.txt
        pip install python-energyzero
        
    - name: Collect multi-source data
      env:
        ENTSOE_API_KEY: ${{ secrets.ENTSOE_API_KEY }}
        TENNET_API_KEY: ${{ secrets.TENNET_API_KEY }}
        OPENWEATHER_API_KEY: ${{ secrets.OPENWEATHER_API_KEY }}
        METEO_API_KEY: ${{ secrets.METEO_API_KEY }}
        ENCRYPTION_KEY_B64: ${{ secrets.ENCRYPTION_KEY_B64 }}
        HMAC_KEY_B64: ${{ secrets.HMAC_KEY_B64 }}
      run: python src/live_data_collector.py
      
    - name: Run market analysis
      run: python src/market_analyzer.py
      
    - name: Update rolling windows
      run: python src/data_manager.py --cleanup
      
    - name: Commit and push results
      run: |
        git config --global user.email "energylivedata@github.com"
        git config --global user.name "energyLiveData Bot"
        git add data/live/
        git diff --staged --quiet || git commit -m "Update live data $(date -u +%Y%m%d-%H%M%S)"
        git push
        
    - name: Trigger dashboard rebuild
      run: |
        curl -X POST -d {} ${{ secrets.DASHBOARD_BUILD_HOOK }}
      continue-on-error: true
      
    - name: Health check notification
      if: failure()
      run: |
        echo "Collection failed at $(date)" >> monitoring/collection_failures.log
```

### Data Collection Implementation
```python
# src/live_data_collector.py
import asyncio
import aiohttp
from typing import Dict, List, Optional
from dataclasses import asdict
from energyzero import EnergyZero

class LiveDataCollector:
    def __init__(self):
        self.collectors = {
            'energy_wholesale': ENTSOECollector(),
            'energy_consumer': EnergyZeroCollector(),
            'grid': TennetCollector(),
            'weather': WeatherCollector(),
            'air_quality': AirQualityCollector()
        }
        self.encryption_handler = SecureDataHandler()
        
    async def collect_all_sources(self) -> LiveEnergySnapshot:
        """Collect data from all sources concurrently"""
        tasks = {
            name: collector.collect_data() 
            for name, collector in self.collectors.items()
        }
        
        results = await asyncio.gather(
            *tasks.values(), 
            return_exceptions=True
        )
        
        # Combine results into unified snapshot
        snapshot_data = self.combine_results(
            dict(zip(tasks.keys(), results))
        )
        
        snapshot = LiveEnergySnapshot(**snapshot_data)
        snapshot.calculate_derived_metrics()
        
        return snapshot
        
    def combine_results(self, results: Dict) -> Dict:
        """Combine multi-source results into unified format"""
        combined = {
            'timestamp': datetime.now(timezone.utc),
            'collection_timestamp': datetime.now(timezone.utc)
        }
        
        # Process each data source
        for source, data in results.items():
            if isinstance(data, Exception):
                logger.error(f"Collection failed for {source}: {data}")
                continue
                
            combined.update(self.extract_fields(source, data))
            
        return combined
        
    def extract_fields(self, source: str, data: Dict) -> Dict:
        """Extract relevant fields from each data source"""
        extracted = {}
        
        if source == 'energy_consumer' and data:
            # Energy Zero specific extraction
            current_pricing = self.collectors['energy_consumer'].extract_current_pricing(data)
            if current_pricing:
                extracted.update(current_pricing)
                
            # Add gas pricing if available
            if data.get('current_gas_prices'):
                # Get current hour gas price
                current_hour = datetime.now().replace(minute=0, second=0, microsecond=0)
                for gas_price in data['current_gas_prices']:
                    if gas_price.datetime.replace(tzinfo=None) == current_hour:
                        extracted['gas_price'] = gas_price.price
                        break
                        
        elif source == 'energy_wholesale' and data:
            # ENTSO-E data extraction
            extracted.update({
                'wholesale_price': data.get('price'),
                'actual_load': data.get('load'),
                'renewable_share': data.get('renewable_percentage')
            })
            
        # ... other source extractions
        
        return extracted
        
    async def store_snapshot(self, snapshot: LiveEnergySnapshot):
        """Store encrypted snapshot and update rolling windows"""
        # Encrypt snapshot
        encrypted_data = self.encryption_handler.encrypt_and_sign(
            asdict(snapshot)
        )
        
        # Store current snapshot
        await self.store_file(
            'data/live/current_snapshot.json',
            encrypted_data
        )
        
        # Update rolling window
        await self.update_rolling_window(snapshot)
        
        # Update market analysis
        await self.update_market_analysis(snapshot)
```

## Energy Zero Integration Details

### API Connection Management
```python
class EnergyZeroCollector:
    def __init__(self):
        self.energyzero = EnergyZero()
        self.session = None
        
    async def ensure_session(self):
        """Ensure aiohttp session is available"""
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()
            
    async def collect_data(self):
        """Main collection method with error handling"""
        try:
            await self.ensure_session()
            
            # Collect current data
            consumer_data = await self.collect_consumer_data()
            
            # Collect forecast data if available
            forecast_data = await self.collect_forecast_data()
            
            return {
                'consumer_pricing': consumer_data,
                'forecast_pricing': forecast_data,
                'collection_success': True,
                'collection_timestamp': datetime.now(timezone.utc)
            }
            
        except Exception as e:
            logger.error(f"Energy Zero collection failed: {e}")
            return {
                'consumer_pricing': None,
                'forecast_pricing': None,
                'collection_success': False,
                'error': str(e),
                'collection_timestamp': datetime.now(timezone.utc)
            }
    
    async def collect_forecast_data(self):
        """Collect tomorrow's pricing if available"""
        tomorrow = datetime.now().date() + timedelta(days=1)
        
        try:
            tomorrow_prices = await self.energyzero.energy_prices(tomorrow, tomorrow)
            return {
                'tomorrow_energy_prices': tomorrow_prices,
                'forecast_available': True
            }
        except Exception as e:
            logger.info(f"Tomorrow's prices not yet available: {e}")
            return {
                'tomorrow_energy_prices': None,
                'forecast_available': False
            }
    
    async def close(self):
        """Clean up session"""
        if self.session and not self.session.closed:
            await self.session.close()
```

### Price Validation & Quality Control
```python
class EnergyZeroPriceValidator:
    def __init__(self):
        self.reasonable_ranges = {
            'consumer_price_total': (0, 2000),    # EUR/MWh
            'consumer_price_energy': (0, 1500),   # EUR/MWh  
            'gas_price': (0, 5),                  # EUR/m³
        }
        
    def validate_energy_zero_data(self, pricing_data) -> Dict[str, bool]:
        """Validate Energy Zero pricing data"""
        validations = {}
        
        if pricing_data and pricing_data.get('consumer_price_total'):
            price_total = pricing_data['consumer_price_total']
            price_energy = pricing_data.get('consumer_price_energy', 0)
            
            # Range validation
            validations['price_total_range'] = self.validate_range(
                'consumer_price_total', price_total
            )
            validations['price_energy_range'] = self.validate_range(
                'consumer_price_energy', price_energy
            )
            
            # Logical validation
            validations['price_logic'] = price_total >= price_energy
            
            # Reasonableness check (taxes/fees should be 20-80% of total)
            if price_total > 0 and price_energy > 0:
                tax_percentage = ((price_total - price_energy) / price_total) * 100
                validations['tax_percentage_reasonable'] = 20 <= tax_percentage <= 80
            else:
                validations['tax_percentage_reasonable'] = False
                
        return validations
        
    def validate_range(self, field: str, value: float) -> bool:
        """Validate value is within reasonable range"""
        if field in self.reasonable_ranges:
            min_val, max_val = self.reasonable_ranges[field]
            return min_val <= value <= max_val
        return True
```

## Performance Optimization

### Concurrent Collection with Energy Zero
```python
async def collect_with_timeout(self, collector, timeout_seconds: int = 30):
    """Collect data with timeout protection - optimized for Energy Zero"""
    try:
        return await asyncio.wait_for(
            collector.collect_data(), 
            timeout=timeout_seconds
        )
    except asyncio.TimeoutError:
        logger.warning(f"Collection timeout for {collector.__class__.__name__}")
        return None
    except Exception as e:
        logger.error(f"Collection error for {collector.__class__.__name__}: {e}")
        return None
    finally:
        # Ensure Energy Zero session cleanup
        if hasattr(collector, 'close'):
            await collector.close()
```

### Caching Strategy for Energy Zero
```python
class EnergyZeroCache:
    def __init__(self):
        self.cache = {}
        self.cache_duration = timedelta(minutes=10)  # Energy Zero updates hourly
        
    async def get_cached_or_fetch(self, date_key: str, fetch_func):
        """Get cached Energy Zero data or fetch if expired"""
        if date_key in self.cache:
            cached_data, timestamp = self.cache[date_key]
            if datetime.now() - timestamp < self.cache_duration:
                return cached_data
                
        # Fetch new data
        fresh_data = await fetch_func()
        self.cache[date_key] = (fresh_data, datetime.now())
        return fresh_data
        
    def clear_old_cache(self):
        """Remove expired cache entries"""
        now = datetime.now()
        expired_keys = [
            key for key, (_, timestamp) in self.cache.items()
            if now - timestamp > self.cache_duration
        ]
        for key in expired_keys:
            del self.cache[key]
```

## Dependencies Update

### requirements.txt
```txt
# Core dependencies
asyncio==3.4.3
aiohttp==3.8.5
python-dateutil==2.8.2
pytz==2023.3
pydantic==2.4.2

# Energy APIs
python-energyzero==0.7.1
entsoe-py==0.5.10

# Weather APIs  
pyowm==3.3.0
requests==2.31.0

# Data processing
pandas==2.1.1
numpy==1.24.3

# Encryption
cryptography==41.0.4

# Logging and monitoring
structlog==23.1.0
```

### Installation Notes
```bash
# Install Energy Zero library
pip install python-energyzero

# Note: Energy Zero requires no authentication
# This simplifies the setup compared to Frank Energie
```

---

*This updated technical implementation guide provides comprehensive instructions for building energyLiveData with Energy Zero integration, maintaining the same powerful market analysis capabilities while simplifying the consumer data collection process.*
```


# docs\energyzero_vs_frank_energie.md
```markdown
# EnergyZero vs Frank Energie API Comparison
## Live Energy Data for the Netherlands

This document compares the APIs of two major Dutch energy providers for retrieving live energy price data: EnergyZero and Frank Energie.

---

## 📊 Quick Comparison

| Feature | EnergyZero | Frank Energie |
|---------|------------|---------------|
| **API Type** | REST | GraphQL |
| **Authentication** | ❌ None required | ⚠️ Required for advanced features |
| **Price Updates** | Every 10 minutes | Real-time |
| **Home Assistant** | ✅ Official integration | ⚠️ Community integration |
| **Documentation** | ✅ Excellent | ⚠️ Limited |
| **Market Coverage** | Multiple providers | Direct wholesale |
| **Smart Features** | Basic automation | Advanced trading |

---

## 🔌 EnergyZero API

### Overview
EnergyZero provides a simple, public API that serves multiple energy providers including ANWB Energie and Energie van Ons. It's designed for transparency and ease of use.

### 🎯 Strengths

#### **No Authentication Required**
- Completely public API at `https://api.energyzero.nl/v1/energyprices`
- No API keys, tokens, or registration needed
- Instant access for developers

#### **Excellent Integration Support**
- Native Home Assistant integration since 2023.2
- Used by 1,409+ active installations
- Well-maintained Python library: [`python-energyzero`](https://github.com/klaasnicolaas/python-energyzero)

#### **Reliable Data Updates**
- Updates every 10 minutes automatically
- New prices published daily around 14:00 UTC for next day
- Consistent availability and uptime

#### **Comprehensive Data**
- Hourly electricity prices
- Daily gas prices  
- Price statistics (min, max, average)
- Percentage comparisons
- Time-based price analysis

### 🔧 Technical Details

#### **API Endpoints**
```http
GET https://api.energyzero.nl/v1/energyprices
```

#### **Parameters**
- `fromDate` - Start date (ISO 8601)
- `tillDate` - End date (ISO 8601) 
- `interval` - Data interval (4=day, 5=month, 6=year, 9=week)
- `usageType` - Usage type (1=electricity, 2=gas)
- `inclBtw` - Include VAT (true/false)

#### **Python Usage Example**
```python
import asyncio
from datetime import date
from energyzero import EnergyZero, VatOption

async def main():
    async with EnergyZero(vat=VatOption.INCLUDE) as client:
        start_date = date(2024, 12, 7)
        end_date = date(2024, 12, 7)
        
        energy = await client.energy_prices(start_date, end_date)
        gas = await client.gas_prices(start_date, end_date)
        
        print(f"Current electricity price: €{energy.current_hour_price}/kWh")
        print(f"Average daily price: €{energy.average_price}/kWh")

asyncio.run(main())
```

### ⚠️ Limitations

- **Basic Price Data Only**: Prices include VAT but exclude energy tax and purchase costs
- **No Personal Data**: Cannot access individual consumption or billing information
- **Limited Smart Features**: Basic automation capabilities only

---

## ⚡ Frank Energie API

### Overview
Frank Energie offers a more sophisticated API focused on dynamic pricing and smart energy management. It provides direct access to wholesale market prices and advanced energy trading features.

### 🎯 Strengths

#### **Real-Time Market Access**
- Direct wholesale market pricing
- Real-time price updates
- Imbalance market integration

#### **Advanced Smart Features**
- EV charging optimization
- Home battery management
- Solar panel optimization
- Virtual Power Plant (VPP) participation

#### **Comprehensive Pricing**
- Market prices and markup information
- Dynamic tariff calculations
- Price forecasting capabilities

#### **Smart Energy Management**
- Automated energy trading
- Grid balancing services
- AI-powered optimization algorithms

### 🔧 Technical Details

#### **API Endpoint**
```http
POST https://graphcdn.frankenergie.nl
```

#### **GraphQL Query Example**
```graphql
query MarketPrices {
  marketPricesElectricity(startDate: "2024-12-01", endDate: "2024-12-30") {
    till
    from
    marketPrice
    priceIncludingMarkup
  }
  marketPricesGas(startDate: "2024-12-01", endDate: "2024-12-30") {
    from
    till
    marketPrice
    priceIncludingMarkup
  }
}
```

#### **Python Usage Example**
```python
import requests

query = """
query MarketPrices {
  marketPricesElectricity(startDate: "2024-12-01", endDate: "2024-12-30") {
    till
    from
    marketPrice
    priceIncludingMarkup
  }
}
"""

response = requests.post(
    'https://graphcdn.frankenergie.nl',
    json={'query': query}
)

data = response.json()
prices = data['data']['marketPricesElectricity']
```

### ⚠️ Limitations

#### **Authentication Complexity**
- No authentication for basic market prices
- Customer account required for advanced features
- Less straightforward setup process

#### **Documentation Gaps**
- Limited public API documentation
- Smaller community support
- Fewer integration examples

#### **Learning Curve**
- GraphQL complexity vs simple REST
- More complex data structures
- Requires understanding of energy trading concepts

---

## 🏆 Use Case Recommendations

### Choose **EnergyZero** for:

#### **Simple Price Monitoring**
- Basic energy price tracking
- Home automation triggers
- Cost optimization alerts
- Historical price analysis

#### **Home Assistant Integration**
- Plug-and-play setup
- Reliable sensor data
- Dashboard visualizations
- Energy cost calculations

#### **Development Simplicity**
- Quick prototyping
- Educational projects
- No authentication barriers
- Well-documented libraries

#### **Multi-Provider Support**
- ANWB Energie customers
- Energie van Ons users
- Generic price monitoring
- Provider-agnostic solutions

### Choose **Frank Energie** for:

#### **Advanced Energy Management**
- Smart EV charging optimization
- Home battery trading
- Solar panel management
- Grid balancing participation

#### **Real-Time Trading**
- Wholesale market access
- Imbalance market participation
- Dynamic pricing strategies
- Professional energy management

#### **Frank Energie Customers**
- Personal consumption data
- Billing information access
- Account management features
- Integrated smart services

#### **Energy Innovation Projects**
- VPP development
- Grid optimization research
- Energy trading algorithms
- Smart grid applications

---

## 📈 Performance Comparison

### **Data Freshness**
- **EnergyZero**: 10-minute intervals, predictable updates
- **Frank Energie**: Real-time updates, market-driven timing

### **Reliability**
- **EnergyZero**: High uptime, stable service, proven track record
- **Frank Energie**: Good reliability, more complex infrastructure

### **Community Support**
- **EnergyZero**: Large community, active development, extensive documentation
- **Frank Energie**: Smaller community, less documentation, specialized use cases

### **Integration Ecosystem**
- **EnergyZero**: Home Assistant, Node-RED, Domoticz, Homey
- **Frank Energie**: Custom integrations, specialized platforms

---

## 🔗 Resources & Libraries

### EnergyZero
- **Python Library**: [python-energyzero](https://github.com/klaasnicolaas/python-energyzero) by Klaas Nicolaas
- **Home Assistant**: Official integration (built-in)
- **Node-RED**: [Energy Zero Flow](https://flows.nodered.org/flow/9960a5c608fba8bc01c091ad04d805c9)
- **API Documentation**: Available in Home Assistant docs

### Frank Energie
- **Python Library**: [python-frank-energie](https://github.com/HiDiHo01/python-frank-energie) by HiDiHo01
- **Home Assistant**: [Custom Component](https://github.com/bajansen/home-assistant-frank_energie)
- **GraphQL Endpoint**: `https://graphcdn.frankenergie.nl`
- **API Examples**: Limited community documentation

---

## 💡 Final Recommendation

### **For Most Users: Choose EnergyZero**

EnergyZero's API is the clear winner for general-purpose energy price monitoring due to:

- **Zero barriers to entry** - no authentication required
- **Excellent documentation** and community support
- **Proven reliability** with thousands of active users
- **Simple integration** with popular home automation platforms

### **For Advanced Users: Consider Frank Energie**

Frank Energie becomes attractive when you need:

- **Real-time market data** for trading applications
- **Advanced smart energy features** for optimization
- **Direct wholesale access** for professional use
- **Integrated energy management** within their ecosystem

The choice ultimately depends on your specific requirements, technical expertise, and whether you prioritize simplicity (EnergyZero) or advanced features (Frank Energie).
```


# LICENSE
```text
MIT License

Copyright (c) 2025 Jeroen Veen

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

```


# README.md
```markdown
# energyLiveData-
A real-time energy data collection system designed to complement the existing energydatahub (day-ahead forecasts) 

```

