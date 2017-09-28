# THis module contaiins codes for retrieving and visualizing various observation types. 
# currently this is pretty kludge-y and contains only quick subroutines that I wrote 
# to do a few things I needed to do. 

# load the required packages  
import numpy as np
import pandas as pd  
import datetime
import experiment_settings as es
import DART as dart
import os.path
#from netCDF4 import Dataset

def HRRS_as_DF(OBS,TPbased=False,TPbased_vertical_res=50E-3,hostname='taurus',debug=False):

	"""
	Loop over a set of dates and a specified latitude- and longitude range, and return 
	the available high-resolution radiosonde data as a pandas data frame  
	
	INPUTS:
	OBS: a dictionary with the following entries:  
		daterange: a list of datetime objects that give the desired date range  
		latrange: a list giving the bounding latitudes of the desired range 
		lonrange: a list giving the bounding longitudes of the desired range 
		Note that OBS can be a DART experiment dictionary (see DART.py), but the DART/model 
			specific entries are ignored. 
	TPbased: set to True to return the profiles ordered into regularly-spaced altitudes 
		relative to the tropopause  - default is False. 
	hostname: default is taurus 
	debug: set to True to print some stuff out. Default is False. 
	TPbased_vertical_res: resolution of the grid to which we inteprolate the obs doing TP-based 
		coordinates. Default is 50m. 
	"""

	# first read in station information as a dataframe 
	stationdata = HRRS_station_data(hostname)
	
	# initialize an empy list which will hold the data frames for each station and time 
	DFlist=[]

	# because the HRRS data are sorted by years, loop over the years in the daterange
	DR=OBS['daterange']
	y0 = DR[0].year
	yf = DR[len(DR)-1].year
	years = range(y0,yf+1,1)
	for YYYY in years:  

		# load a list of the available stations for that year  
		Slist  = HRRS_stations_available_per_year(YYYY)

		# trim list down to the ones that fit into the latitude range 
		stations_lat = [s for s in Slist 
				if stationdata.loc[int(s)]['Lat'] >= OBS['latrange'][0] 
				and stationdata.loc[int(s)]['Lat'] <= OBS['latrange'][1] ]

		# trim list down to the ones that fit into the longitude range 
		stations_latlon = [s for s in stations_lat
				if stationdata.loc[int(s)]['Lon'] >= OBS['lonrange'][0] 
				and stationdata.loc[int(s)]['Lon'] <= OBS['lonrange'][1] ]

		# also compute the subset of the requested daterange that fits into this year. 
		year_daterange =  dart.daterange(date_start=datetime.datetime(YYYY,1,1,0,0,0), periods=365*4, DT='6H')
		DR2 = set(year_daterange).intersection(DR)
		
		# also find the dir where the station data live 
		datadir = es.obs_data_paths('HRRS',hostname)

		# now loop over available stations, and for each one, retrieve the data 
		# that fit into the requested daterange 
		for s in stations_latlon:	

			# loop over dates, and retrieve data if available 
			for dd in DR2:
				datestr = dd.strftime("%Y%m%d%H")
				ff = datadir+'/'+str(YYYY)+'/'+str(s)+'/'+str(s)+'-'+datestr+'_mod.dat'
				if os.path.exists(ff):

					if debug:
						print(ff)

					# read in the station data 
					if TPbased:
						D = TP_based_HRRS_data(ff,vertical_res_km=TPbased_vertical_res)
						alt_to_km = 1.0    # here the altitude is already in km
						temp_to_K = 0.0
					else:
						D = read_HRRS_data(ff)
						alt_to_km = 1.0E-3     # raw data are in m -- convert to km 
						temp_to_K = 273.15	# raw data need to be converted to kelvin
		
					if D is not None:
						# also add a column holding the date 
						D['Date'] = pd.Series(dd, index=D.index)

						# also add a column holding the station number 
						D['StationNumber'] = pd.Series(s, index=D.index)

						# make sure altitude is in km 
						# and temp in Kelvin
						D['Alt']=D['Alt']*alt_to_km
						D['Temp']=D['Temp']+temp_to_K
					
						# get rid of some unneeded columns 
						if not TPbased:
							useless_cols=['Time','Dewpt','RH','Ucmp','Vcmp','spd','dir', 
									'Wcmp',  'Ele', 'Azi', 'Qp', 'Qt', 'Qrh', 'Qu', 'Qv', 'QdZ']
							D.drop(useless_cols,inplace=True,axis=1)

						# append to list of data frames 
						DFlist.append(D)


	# merge the list of data frames into a single DF using list comprehension 
	DFout = pd.concat(DFlist, axis=0)

	return(DFout)

def TP_based_HRRS_data(ff,vertical_res_km=50E-3,debug=False,hostname='taurus'):

	"""
	Given a single high-res radiosonde data sounding (identified by its 
	full file path, ff) 
	load the data from the sounding and compute the temperature data 
	as a function of distance from the thermal tropopause. 
	This is done by:  
	1. reading in the data as a pandas data frame  
	2. computing the height of the tropopause 
	3. computin the altitude of each data point relative to the tropopause 
	4. using a cubic spline to create evenly-spaced temperatures on a vertical 
	 grid with 50m spacing. 

	This procedure is based on Birner et al. 2002 (http://doi.wiley.com/10.1029/2002GL015142)  

	Here the LR tropopause follows the WMO criterion. Quoting Birner et al. (2002):
	The thermal TP is defined as the lowest level where the temperature lapse rate falls 
	below 2 K/km and its average between this level and all higher levels within 2 km remains below this value [WMO, 1957]. 

	INPUTS:  
	ff: the full path to the HRRS profile that we will load 
	vertical_res_km: vertical resolution of the grid to which we interpolate, in km. The default is 50m, which is roughly the vertical resolution of the HRRS obs. 
	"""

	# read in the data as a data frame 
	DF0 = read_HRRS_data(ff)

	# drop unnecessary columns 
	useless_cols=['Time','Dewpt','RH','Ucmp','Vcmp','spd','dir','Lat','Lon', 
			'Wcmp',  'Ele', 'Azi', 'Qp', 'Qt', 'Qrh', 'Qu', 'Qv', 'QdZ']
	DF0.drop(useless_cols,inplace=True,axis=1)

	# get rid of NaNs
	DF=DF0.dropna()

	if debug:
		print('Loading file '+ff)

	# load interpolate function from scipy
	from scipy.interpolate import interp1d

	# compute the height of the lapse-tropopause from the altitude array 
	z=DF['Alt']/1E3       # Altitude in km 
	T=DF['Temp']+273.15      # Temp in Kelvin
	P=DF['Press']
	N2=DF['N2']

	from TIL import ztrop
	ztropp=ztrop(z=z,T=T,debug=debug,hostname=hostname)

	if ztropp is not None:

		# extract the station number from the file path 
		file_components=ff.split('/')
		station=file_components[len(file_components)-2]

		# retrieve the mean tropopause height for this station 
		# TODO: right noew this reads in a csv file of mean heights for Jan 2010. 
		#	...need to make this more dynamic and obviously not user and host specific 
		ZT=pd.read_csv('/data/c1/lneef/HRRS//mean_tropopause_height_per_station_20100101-20100131.csv',index_col=0)
		ztrop_mean = ZT.loc[int(station)].ztrop_mean

		# now compute the altitude relative to the tropopause, plus mean tropopause height 
		zTP = DF['Alt']*1E-3-ztropp+ztrop_mean

		# interpolate temp, pressure to this new coordinate
		fT = interp1d(zTP, T, kind='linear')
		fP = interp1d(zTP, P, kind='linear')

		# create a regularly spaced grid (in km) 
		zTPgrid=np.arange(0.0,26.0, vertical_res_km)

		# select whatever part of the regular grid fits into the range sampled by this sounding 
		select = np.where(np.logical_and(zTPgrid>min(zTP), zTPgrid<max(zTP)))
		zTPnew=zTPgrid[select]

		# now compute the variables on this grid using the interpolate function 
		Tnew = fT(zTPnew)
		Pnew = fP(zTPnew)

		# N2 comes out quite noisy when computed from raw radiosonde observations. 
		# The spline (needed to get the obs on a common grid) is an opportunity for smoothing 
		# the temperature field a bit, which will yield a smoother N2 profile -- so just recompute 
		# N2 here  
		from TIL import Nsq
		N2new = Nsq(Tnew,zTPnew,Pnew)

		# now create a new dataframe with the TP-based heights 
		new_data={'Press':Pnew,'Temp':Tnew,'Alt':zTPnew,'N2':N2new,'ztropp':ztropp}
		Dout = pd.DataFrame(data=new_data) 
	else:
		if debug:
			print('No clear lapse-rate tropopause found for the following sounding:')
			print(ff)
			print('Returning None')
		Dout=None

	return(Dout)

def HRRS_mean_ztrop_to_csv(DR,hostname='taurus',debug=False):

	"""
	Given a certain daterange, retrieve available high res radiosonde data,
	compute the average tropopause height per station, and store in a 
	csv file. 
	"""
	from TIL import ztrop

	# first read in station information as a dataframe 
	stationdata = HRRS_station_data(hostname)

	# because the HRRS data are sorted by years, loop over the years in the daterange
	y0 = DR[0].year
	yf = DR[len(DR)-1].year
	years = range(y0,yf+1,1)
	for YYYY in years:  

		# load a list of the available stations for that year  
		Slist  = HRRS_stations_available_per_year(YYYY)

		# also compute the subset of the requested daterange that fits into this year. 
		year_daterange =  dart.daterange(date_start=datetime.datetime(YYYY,1,1,0,0,0), periods=365*4, DT='6H')
		DR2 = set(year_daterange).intersection(DR)
		
		# also find the dir where the station data live 
		datadir = es.obs_data_paths('HRRS',hostname)

		# initialize empty dictionary to hold average tropoopause heights per station 
		ztrop_dict=dict()

		# now loop over available stations, and for each one, retrieve the data 
		# that fit into the requested daterange 

		for s in Slist:	
			ztrop_list=[]	# empty list to hold tropopause heights for all available obs per station 

			# loop over dates, and retrieve data if available 
			for dd in DR2:
				datestr = dd.strftime("%Y%m%d%H")
				ff = datadir+'/'+str(YYYY)+'/'+str(s)+'/'+str(s)+'-'+datestr+'_mod.dat'
				if os.path.exists(ff):

					if debug:
						print(ff)

					# read in the station data 
					D = read_HRRS_data(ff)
	
					# compute tropopause height 
					z=D['Alt']/1E3       # Altitude in km 
					T=D['Temp']+273.15      # Temp in Kelvin
					ztropp=ztrop(z=z,T=T,debug=debug,hostname=hostname)

					# add to list if not none  
					if ztropp is not None:
						ztrop_list.append(ztropp)

			# average the tropopause heights and add to dictionary 
			ztrop_dict[s]=np.mean(ztrop_list)

		# turn dict into data frame  
		ZT=pd.Series(data=ztrop_dict, name='ztrop_mean')

		if debug:
			print(ZT)

		# turn dataframe into csv file
		hrrs_path = es.obs_data_paths('HRRS',hostname)
		datestr = DR[0].strftime("%Y%m%d")+'-'+DR[len(DR)-1].strftime("%Y%m%d")+'.csv'
		fname=hrrs_path+'/'+'mean_tropopause_height_per_station_'+datestr
		print('storing file '+fname)
		ZT.to_csv(fname, index=True, sep=',',header=True) 

		return(ZT)

def read_HRRS_data(ff):

	"""
	Read in a .dat file from SPARC high-res radiosonde data 
	Input ff is a string pointing to the full path of the desired file. 
	"""

	# here is a dict that gives bad values for different columns 
	# alert: this is still incomplete 
	badvals = {'Temp':['999.0'],'Alt':['99.0','99999.0'],'Lat':['999.000'],'Lon':['9999.000']}
	
	D= pd.read_csv(ff,skiprows=13,error_bad_lines=False,delim_whitespace=True,na_values=badvals)
	colnames=list(D.columns.values)

	# kick out the first two rows - they hold units and symbols 
	D.drop(D.index[[0,1]], inplace=True)

	# also make sure that lat, lon, pressure, altitude, and temp are numerics 
	vars_to_float = ['Press','Temp','Lat','Lon','Alt']
	D[vars_to_float] = D[vars_to_float].astype(float)

	# compute the vertical gradient of potential temp and, from that, buoyancy frequency 
	P0=1000.0
	Rd = 286.9968933                # Gas constant for dry air        J/degree/kg
	g = 9.80616                     # Acceleration due to gravity       m/s^2
	cp = 1005.0                     # heat capacity at constant pressure    m^2/s^2*K
	theta=(D['Temp']+273.15)*(P0/D['Press'])**(Rd/cp)		# note that this includes conversion of Celsius to Kelvin  
	dZ = np.gradient(D['Alt']) 
	dthetadZ = np.gradient(theta,dZ)
	D["N2"]=(g/theta)*dthetadZ
	

	return(D)

def HRRS_stations_available_per_year(YYYY):

	"""
	Given a specific calendar year (in integer form), return a list of the available 
	high-res radiosonde stations for that year 

	TODO: so far only have 2010 coded in ...need to add others 
	"""

	stations_avail_dict={2010:['03160','04102','12850','14607','14918',
					'22536','25624','26510','26616','40308','40504',
					'40710','61705','03190','11641','13985','14684',
					'21504','25501','25713','26615','27502','40309',
					'40505','41406']
           			}

	return(stations_avail_dict[YYYY])

def HRRS_station_data(hostname='taurus'):

	"""
	Read in information about the high-res radiosondes and return it as a pandas dataframe.
	"""
	
	datadir = es.obs_data_paths('HRRS',hostname)

	ff=datadir+'ListOfStations.dat'
	colnames=[ 'WBAN','Station_Name','State','Country','WMO_Code','Lat','Lon','Height','Transition date']
	stations = pd.read_csv(ff,delimiter=",",error_bad_lines=False,skiprows=1,names=colnames,index_col='WBAN')


	# a few columns have to be coerced to numeric 
	stations[['Lat','Lon']] = stations[['Lat','Lon']].apply(pd.to_numeric, errors='coerce')

	return(stations)

def read_COSMIC_TPbased_mean(E,hostname='taurus'):

	"""	
	Read in COSMIC temp and N2 data averaged with respect to the local tropopause. 
	"""	

	from netCDF4 import Dataset

	# find the path to the data  
	datadir = es.obs_data_paths('COSMIC',hostname)

	# TODO: right now this loads the only file I have. Later can code a dynamic way to 
	# choose files based on what is specified in E. 
	ff = 'mean_GPS-RO_45-60N_COSMIC_Jan2010_TPbased_mean.nc'
	filename=datadir+ff

	# open the file and read in the relevant data into dict
	D = dict()
	f = Dataset(filename,'r')

	varnames = {'T':'T',
			'Nsq':'N2'}
	variable = varnames[E['variable']]

	D['z'] = f.variables['z'][:]
	D['data'] = f.variables[variable][:]
	D['units']= f.variables[variable].units

	# one last thing! Convert Celsius to Kelvin  
	if 'Celsius' in f.variables[variable].units:
		D['data']=f.variables[variable][:]+273.5
		D['units']='K'

	f.close()

	return D

