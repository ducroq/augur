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
        